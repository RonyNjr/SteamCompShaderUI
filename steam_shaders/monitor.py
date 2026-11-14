#!/usr/bin/env python3
"""Acompanha os shaders da Steam no Linux, usando a biblioteca padrão do Python."""

import argparse
from dataclasses import dataclass, field
from datetime import datetime
import fcntl
import html
import json
import logging
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import threading
import time
import uuid

from .support import VERSION, data_dir, discover_steam, load_config, steam_candidates

LOG = logging.getLogger("steam-shaders")
COMPLETION_DELAY = 15
STALE_PROGRESS = 30
MISSING_PROCESS_DELAY = 45
STATUS_HEARTBEAT = 10  # As interfaces consideram o estado antigo depois de 20 s.
MARKERS = (b"Starting processing job", b"Still replaying", b"fossilize_replay completed",
           b"Destroyed compile job")
EVENT_RE = re.compile(
    r"^\[([^]]+)\] (?:"
    r"Starting processing job for app (?P<start>\d+)!|"
    r"Still replaying (?P<progress>\d+) \((?P<pct>\d+)%, (?P<done>\d+)/(?P<total>\d+)\)\.|"
    r"\[\s*App ID (?P<complete>\d+)\s*\] fossilize_replay completed.*|"
    r"Destroyed compile job (?P<destroy>\d+)\.?)$")


def parse_event(line):
    match = EVENT_RE.match(line.strip())
    if not match:
        return None
    try:
        stamp = datetime.strptime(match[1], "%Y-%m-%d %H:%M:%S").timestamp()
    except ValueError:
        return None
    kind = next(key for key in ("start", "progress", "complete", "destroy") if match[key])
    event = {"kind": kind, "appid": match[kind], "at": stamp}
    if kind == "progress":
        event.update(percent=min(100, int(match["pct"])), done=int(match["done"]),
                     total=int(match["total"]))
    return event


def read_vdf(text):
    """Lê objetos KeyValues, incluindo nomes e caminhos com escapes."""
    tokens = re.finditer(r'"(?P<quoted>(?:\\.|[^"\\])*)"|(?P<brace>[{}])|(?P<comment>//[^\n]*)', text)
    root, stack, key = {}, [], None
    current = root
    for token in tokens:
        if token["comment"] is not None:
            continue
        quoted, brace = token["quoted"], token["brace"]
        if brace == "{":
            if key is None:
                continue
            child = {}
            current[key] = child
            stack.append(current)
            current, key = child, None
        elif brace == "}":
            current = stack.pop() if stack else root
            key = None
        elif quoted is not None:
            value = re.sub(r'\\([\\"])', r'\1', quoted)
            if key is None:
                key = value
            else:
                current[key], key = value, None
    return root


class GameNames:
    def __init__(self, steam):
        self.steam = Path(steam)
        self.cache = {}
        self.refreshed = 0

    def get(self, appid):
        if appid is None:
            return "Jogo não identificado"
        if time.monotonic() - self.refreshed > 60:
            self.cache.clear()
            self.refreshed = time.monotonic()
        if appid in self.cache:
            return self.cache[appid]
        libraries = [self.steam]
        try:
            data = read_vdf((self.steam / "steamapps/libraryfolders.vdf").read_text(encoding="utf-8"))
            for entry in data.get("libraryfolders", {}).values():
                if isinstance(entry, dict) and "path" in entry:
                    libraries.append(Path(entry["path"]))
                elif isinstance(entry, str) and entry.startswith("/"):
                    libraries.append(Path(entry))  # Formato antigo do libraryfolders.vdf.
        except (OSError, ValueError):
            pass
        for library in dict.fromkeys(libraries):
            try:
                data = read_vdf((library / f"steamapps/appmanifest_{appid}.acf").read_text(encoding="utf-8"))
                name = data.get("AppState", {}).get("name")
                if isinstance(name, str) and name:
                    self.cache[appid] = name
                    return name
            except (OSError, ValueError):
                continue
        return f"AppID {appid}"


@dataclass
class Processes:
    steam: bool = False
    replay: bool = False
    appids: set = field(default_factory=set)

    def matches(self, appid):
        return self.replay and (not self.appids or appid in self.appids or appid is None)


def inspect_processes(proc=Path("/proc")):
    result = Processes()
    try:
        directories = list(proc.iterdir())
    except OSError as error:
        LOG.warning("Não foi possível consultar processos em %s: %s", proc, error)
        return result
    for directory in directories:
        if not directory.name.isdecimal():
            continue
        try:
            if directory.stat().st_uid != os.getuid():
                continue  # Uma sessão de outro usuário não pertence a este monitor.
            comm = (directory / "comm").read_text().strip()
            if comm == "steam":
                result.steam = True
            if not comm.startswith("fossilize_repl"):
                continue
            args = (directory / "cmdline").read_bytes().split(b"\0")
            if not args or not Path(os.fsdecode(args[0])).name.startswith("fossilize_replay"):
                continue
            result.replay = True
            try:
                env = dict(item.split(b"=", 1) for item in
                           (directory / "environ").read_bytes().split(b"\0") if b"=" in item)
            except OSError:
                env = {}
            appid = env.get(b"SteamAppId", env.get(b"SteamGameId", b""))
            if appid.isdigit() and int(appid) > 0:
                result.appids.add(appid.decode())
            else:
                match = re.search(rb"/shadercache/(\d+)/", b" ".join(args))
                if match:
                    result.appids.add(match[1].decode())
        except (OSError, ValueError):
            continue  # O processo pode terminar entre as leituras.
    return result


class LogFollower:
    """Mantém o descritor antigo aberto durante rotação e salva o cursor."""
    def __init__(self, path, cursor=None):
        self.path = Path(path)
        self.previous = self.path.with_name("shader_log.previous.txt")
        self.saved = cursor
        self.stream = None
        self.buffer = b""
        self.seen = set()
        self.initial = True
        self.anchor = ""

    @staticmethod
    def identity(stat):
        return (stat.st_dev, stat.st_ino)

    def _open(self, path):
        self.stream = path.open("rb", buffering=0)
        self.buffer = b""
        stat = os.fstat(self.stream.fileno())
        ident = self.identity(stat)
        self.seen.add(ident)
        if self.saved and tuple(self.saved.get("identity", ())) == ident:
            offset = self.saved.get("offset", 0)
            anchor = bytes.fromhex(self.saved.get("anchor", ""))
            if (len(anchor) <= offset <= stat.st_size and
                    os.pread(self.stream.fileno(), len(anchor), offset - len(anchor)) == anchor):
                self.stream.seek(offset)
            else:
                LOG.warning("Log truncado ou reescrito; relendo o arquivo disponível.")
        self.anchor = self.cursor()["anchor"]

    def _drain(self):
        lines = []
        # Limite por rodada: uma enxurrada de ruído não prende o serviço.
        for _ in range(32):
            chunk = self.stream.read(262144)
            if not chunk:
                break
            parts = (self.buffer + chunk).split(b"\n")
            self.buffer = parts.pop()
            for line in parts:
                if any(marker in line for marker in MARKERS):
                    lines.append(line.decode("utf-8", errors="replace"))
        self.anchor = self.cursor()["anchor"]
        return lines

    def poll(self):
        lines = []
        if self.initial:
            self.initial = False
            try:
                current_id = self.identity(self.path.stat())
            except FileNotFoundError:
                current_id = None
            resume_current = self.saved and tuple(self.saved.get("identity", ())) == current_id
            if not resume_current and self.previous.exists():
                self._open(self.previous)
                lines.extend(self._drain())
        if self.stream:
            stat = os.fstat(self.stream.fileno())
            offset = self.stream.tell() - len(self.buffer)
            anchor = self.anchor
            # pread também detecta truncate + reescrita que já ultrapassou o cursor.
            if stat.st_size < self.stream.tell() or (anchor and
                    os.pread(self.stream.fileno(), len(bytes.fromhex(anchor)),
                             offset - len(bytes.fromhex(anchor))).hex() != anchor):
                self.stream.seek(0)
                self.buffer = b""
            lines.extend(self._drain())
        try:
            current_id = self.identity(self.path.stat())
        except FileNotFoundError:
            return lines
        if self.stream and self.identity(os.fstat(self.stream.fileno())) == current_id:
            return lines
        if self.stream:
            self.close()
        # Se houve duas rotações, tenta salvar também o arquivo intermediário.
        try:
            if self.previous.exists() and self.identity(self.previous.stat()) not in self.seen:
                self._open(self.previous)
                lines.extend(self._drain())
                self.close()
        except FileNotFoundError:
            pass
        self._open(self.path)
        lines.extend(self._drain())
        return lines

    def cursor(self):
        if not self.stream or self.stream.closed:
            return self.saved
        offset = self.stream.tell() - len(self.buffer)
        anchor = os.pread(self.stream.fileno(), min(offset, 64), max(0, offset - 64))
        return {"identity": list(self.identity(os.fstat(self.stream.fileno()))),
                "offset": offset, "anchor": anchor.hex()}

    def close(self):
        if self.stream and not self.stream.closed:
            self.saved = self.cursor()
            self.stream.close()
        self.stream = None


def stage_for(percent):
    return 1 if percent < 33 else 2 if percent < 66 else 3


class Tracker:
    def __init__(self, saved=None):
        saved = saved or {}
        self.active = saved.get("active")
        self.pending = saved.get("pending", {})
        self.watermark = saved.get("watermark", 0)
        self.last_complete = saved.get("last_complete", {})
        self.finished = []
        self.notifications = []

    @staticmethod
    def new_job(appid, stamp, known=True):
        session_id = uuid.uuid5(uuid.NAMESPACE_URL, f"steam-shaders:{appid}:{stamp}").hex
        return {"id": session_id, "appid": appid, "started_at": stamp,
                "start_known": known, "last_at": stamp, "percent": None,
                "done": None, "total": None, "stage": None, "samples": [], "cycles": 1}

    def _finish(self, job, outcome, stamp):
        row = {key: value for key, value in job.items()
               if key not in ("samples", "missing_since", "notify", "complete_at")}
        row.update(outcome=outcome, ended_at=stamp)
        self.finished.append(row)
        return row

    def feed(self, event, live=True):
        kind, appid, stamp = event["kind"], event["appid"], event["at"]
        if stamp < self.watermark:
            return
        self.watermark = stamp
        if kind in ("start", "progress"):
            if self.active and stamp < self.active["last_at"]:
                return
            if self.active and self.active["appid"] is None:
                self.active["appid"] = appid
            if self.active and self.active["appid"] != appid:
                self._finish(self.active, "interrupted", stamp)
                self.active = None
            previous = self.pending.get(appid)
            if previous and stamp < previous["complete_at"]:
                return
            if previous:
                self.active = self.pending.pop(appid)
                self.active.pop("complete_at", None)
                self.active.pop("notify", None)
                self.active["cycles"] += 1
                self.active.update(percent=None, done=None, total=None, stage=None, samples=[])
            if self.active is None:
                self.active = self.new_job(appid, stamp, known=kind == "start")
            job = self.active
            if kind == "start":
                if job["last_at"] < stamp:
                    job.update(percent=None, done=None, total=None, stage=None, samples=[])
            else:
                stage = stage_for(event["percent"])
                if (job["stage"] != stage or
                        (job["done"] is not None and event["done"] < job["done"])):
                    job["samples"] = []
                samples = job["samples"]
                if not samples or stamp > samples[-1][0]:
                    samples.append([stamp, event["done"]])
                job["samples"] = [sample for sample in samples if stamp - sample[0] <= 60][-12:]
                job.update(percent=event["percent"], done=event["done"], total=event["total"], stage=stage)
            job["last_at"] = stamp
            job.pop("missing_since", None)
        elif kind == "complete":
            same_second_cycle = (self.active and self.active["appid"] == appid and
                                 self.active["cycles"] > 1 and
                                 stamp == self.last_complete.get(appid))
            if appid in self.pending or (stamp <= self.last_complete.get(appid, 0) and
                                        not same_second_cycle):
                return
            self.last_complete[appid] = stamp
            if self.active and self.active["appid"] == appid:
                if stamp < self.active["last_at"]:
                    return
                job, self.active = self.active, None
            else:
                job = self.new_job(appid, stamp, known=False)
            job.update(complete_at=stamp, notify=live, last_at=stamp)
            self.pending[appid] = job
        elif kind == "destroy" and self.active and self.active["appid"] == appid:
            if stamp >= self.active["last_at"]:
                self._finish(self.active, "interrupted", stamp)
                self.active = None

    def tick(self, now, processes):
        for appid, job in list(self.pending.items()):
            if now - job["complete_at"] < COMPLETION_DELAY:
                continue
            if processes.matches(appid) and not (not processes.appids and self.active and
                                                  self.active["appid"] != appid):
                continue
            row = self._finish(job, "completed", job["complete_at"])
            if job.get("notify") and 0 <= now - job["complete_at"] < 300:
                self.notifications.append(row)
            del self.pending[appid]
        if self.active:
            job = self.active
            if processes.matches(job["appid"]):
                job.pop("missing_since", None)
            else:
                job.setdefault("missing_since", min(now, job["last_at"]))
                delay = 10 if not processes.steam else MISSING_PROCESS_DELAY
                if now - max(job["last_at"], job["missing_since"]) >= delay:
                    self._finish(job, "interrupted", now)
                    self.active = None
        elif processes.replay and not self.pending:
            appid = sorted(processes.appids)[0] if processes.appids else None
            self.active = self.new_job(appid, now, known=False)

    def checkpoint(self):
        return {"active": self.active, "pending": self.pending,
                "watermark": self.watermark, "last_complete": self.last_complete}

    def snapshot(self, now, names):
        status, job = "idle", self.active
        if job:
            status = "compiling"
        elif self.pending:
            status = "finishing"
            job = max(self.pending.values(), key=lambda item: item["complete_at"])
        active = None
        if job:
            rate, eta = None, None
            samples = job["samples"]
            stale = now - job["last_at"] > STALE_PROGRESS
            if status == "compiling" and not stale and len(samples) >= 2:
                delta = samples[-1][0] - samples[0][0]
                if delta > 0:
                    rate = max(0, (samples[-1][1] - samples[0][1]) / delta)
                    if rate > 0 and job["total"] is not None:
                        eta = max(0, job["total"] - job["done"]) / rate
            active = {key: value for key, value in job.items() if key not in
                      ("samples", "notify", "missing_since")}
            active.update(name=names.get(job["appid"]), rate=rate, eta_seconds=eta,
                          elapsed_seconds=max(0, (job.get("complete_at", now) - job["started_at"])),
                          stale=stale)
        return {"version": 1, "updated_at": now, "status": status, "active": active}


class History:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY, appid TEXT, name TEXT NOT NULL, started_at REAL NOT NULL,
            ended_at REAL NOT NULL, start_known INTEGER NOT NULL, outcome TEXT NOT NULL,
            cycles INTEGER NOT NULL)""")
        self.db.commit()

    def add(self, row, names):
        self.db.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (row["id"], row["appid"], names.get(row["appid"]), row["started_at"],
                         row["ended_at"], row["start_known"], row["outcome"], row["cycles"]))
        self.db.commit()

    def recent(self):
        self.db.row_factory = sqlite3.Row
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM sessions ORDER BY ended_at DESC LIMIT 5")]

    def close(self):
        self.db.close()


def atomic_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


class ChangedWriter:
    """Grava só quando o conteúdo muda ou, com heartbeat, quando o último registro envelhece."""
    def __init__(self, path, heartbeat=None):
        self.path, self.heartbeat = path, heartbeat
        self.last, self.written_at = None, None

    def write(self, data, now, ignore=()):
        # Serializar também detecta mudanças em dicionários alterados no lugar.
        content = json.dumps({key: value for key, value in data.items() if key not in ignore},
                             ensure_ascii=False, sort_keys=True)
        # abs(): um relógio que volta no tempo também força uma nova gravação.
        expired = (self.heartbeat is not None and self.written_at is not None and
                   abs(now - self.written_at) >= self.heartbeat)
        if content == self.last and not expired:
            return False
        atomic_json(self.path, data)
        self.last, self.written_at = content, now
        return True


def load_checkpoint(path):
    try:
        saved = json.loads(path.read_text())
        return saved if saved.get("version") == 1 else {}
    except (OSError, ValueError, AttributeError):
        return {}


def notify(row, names):
    name = html.escape(names.get(row["appid"]))
    body = f"Processamento de shaders de {name} concluído."
    try:
        subprocess.run(["notify-send", "--app-name=Steam Shaders", "--icon=applications-games-symbolic",
                        "Shaders concluídos", body], timeout=5, check=True)
    except (OSError, subprocess.SubprocessError) as error:
        LOG.warning("Não foi possível enviar a notificação: %s", error)


def run(args, stop_event=None, on_notification=None, register_signals=True):
    args.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (args.data_dir / "monitor.lock").open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("O monitor já está em execução neste diretório.") from None
        lock.seek(0)
        lock.truncate()
        lock.write(json.dumps({"pid": os.getpid(), "started":
                              Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19]}))
        lock.flush()
        _run_locked(args, stop_event, on_notification, register_signals)


def _run_locked(args, stop_event, on_notification, register_signals):
    state_path = args.data_dir / "checkpoint.json"
    saved = load_checkpoint(state_path)
    automatic = args.steam_dir is None
    found = discover_steam() if automatic else [args.steam_dir]
    steam = found[0] if found else steam_candidates()[0]
    if saved.get("steam_dir") and saved["steam_dir"] != str(steam):
        saved = {}  # O cursor e o watermark pertencem a uma instalação da Steam.
    tracker = Tracker(saved.get("tracker"))
    names = GameNames(steam)
    follower = LogFollower(steam / "logs/shader_log.txt", saved.get("cursor"))
    history = History(args.data_dir / "history.sqlite3")
    # Sem compilação, evita gravar no disco a cada ciclo (bateria e SSD do Steam Deck).
    checkpoint_writer = ChangedWriter(state_path)
    status_writer = ChangedWriter(args.data_dir / "status.json", heartbeat=STATUS_HEARTBEAT)
    stopping = stop_event if stop_event is not None else threading.Event()
    next_discovery = 0
    if not found:
        LOG.info("Steam ainda não encontrada; aguardando a instalação ou --steam-dir.")
    else:
        LOG.info("Steam: %s", steam)

    def stop(_signum, _frame):
        stopping.set()

    if register_signals:
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
    initial = True
    try:
        while not stopping.is_set():
            now = time.time()
            # Permite instalar/iniciar a Steam depois que a sessão gráfica já abriu.
            if automatic and not found and time.monotonic() >= next_discovery:
                found = discover_steam()
                next_discovery = time.monotonic() + 30
                if found:
                    steam = found[0]
                    follower.close()
                    follower = LogFollower(steam / "logs/shader_log.txt")
                    names = GameNames(steam)
                    tracker = Tracker()
                    initial = True
                    LOG.info("Steam encontrada: %s", steam)
            try:
                lines = follower.poll()
            except OSError as error:
                LOG.warning("Não foi possível ler o log: %s", error)
                lines = []
            for line in lines:
                event = parse_event(line)
                if event:
                    tracker.feed(event, live=not initial or bool(saved))
            initial = False
            tracker.tick(now, inspect_processes())
            for row in tracker.finished:
                history.add(row, names)
                LOG.info("AppID %s: %s", row["appid"], row["outcome"])
            tracker.finished.clear()
            checkpoint_writer.write({"version": 1, "steam_dir": str(steam), "tracker": tracker.checkpoint(),
                                     "cursor": follower.cursor()}, now)
            snapshot = tracker.snapshot(now, names)
            snapshot.update(steam_dir=str(steam), steam_found=steam.is_dir(),
                            log_available=follower.path.is_file())
            snapshot["recent"] = history.recent()
            status_writer.write(snapshot, now, ignore=("updated_at",))
            for row in tracker.notifications:
                if on_notification:
                    on_notification(row, names)
                elif not args.no_notifications:
                    notify(row, names)
            tracker.notifications.clear()
            if args.once:
                break
            stopping.wait(2)
    finally:
        follower.close()
        history.close()
        if stopping.is_set():
            atomic_json(args.data_dir / "status.json", {
                "version": 1, "updated_at": time.time(), "status": "idle", "active": None,
                "monitor_stopped": True,
            })


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--steam-dir", type=Path, help="Diretório da Steam (padrão: detecção automática)")
    parser.add_argument("--data-dir", type=Path, default=data_dir())
    parser.add_argument("--once", action="store_true", help="Uma leitura para diagnóstico")
    parser.add_argument("--no-notifications", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = load_config()
    except ValueError as error:
        parser.error(str(error))
    if args.steam_dir is None and config.get("steam_dir"):
        args.steam_dir = Path(config["steam_dir"])
    if args.steam_dir is not None:
        args.steam_dir = args.steam_dir.expanduser().resolve()
    args.data_dir = args.data_dir.expanduser().resolve()
    args.no_notifications = args.no_notifications or not config.get("notifications", True)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run(args)


if __name__ == "__main__":
    main()
