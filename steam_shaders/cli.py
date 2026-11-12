#!/usr/bin/env python3
"""Comando steam-shaders: progresso e diagnóstico em qualquer desktop Linux."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .support import APP_ID, VERSION, config_path, data_dir, discover_steam, load_config


def read_status(directory):
    try:
        snapshot = json.loads((directory / "status.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError("Nenhum estado encontrado. Inicie o monitor com steam-shaders run.") from None
    except (OSError, ValueError) as error:
        raise ValueError(f"Não foi possível ler o estado: {error}") from error
    if not isinstance(snapshot, dict) or snapshot.get("version") != 1:
        raise ValueError("Formato de estado incompatível.")
    updated = snapshot.get("updated_at")
    if not isinstance(updated, (float, int)) or not -5 <= time.time() - updated <= 20:
        raise ValueError("O estado está desatualizado; confira se o monitor está em execução.")
    if snapshot.get("monitor_stopped"):
        raise ValueError("O monitor está parado.")
    return snapshot


def status(args):
    snapshot = read_status(args.data_dir)
    if args.json:
        print(json.dumps(snapshot, ensure_ascii=False))
        return
    job = snapshot.get("active")
    if not job:
        if not snapshot.get("steam_found", True):
            print("Steam ainda não encontrada. Use steam-shaders doctor para conferir os caminhos.")
        elif not snapshot.get("log_available", True):
            print("Aguardando o log de shaders da Steam. Abra a Steam com o pré-cache habilitado.")
        else:
            print("Nenhuma compilação de shaders em andamento.")
        return
    percent = job.get("percent")
    progress = f"{percent}%" if percent is not None else "progresso ainda não informado"
    print(f"{job['name']}: {progress}")
    if snapshot["status"] == "finishing":
        print("Confirmando conclusão…")
    elif job.get("eta_seconds") is not None:
        print(f"Estimativa da etapa atual: {round(job['eta_seconds'])} s")
    elif job.get("stale"):
        print("Processo detectado; aguardando atualização do log.")


def doctor():
    from .installer import gnome_supported, systemd_available
    from shutil import which

    config = load_config()
    found = [Path(config["steam_dir"]).expanduser()] if config.get("steam_dir") else discover_steam()
    print(f"Steam Shaders {VERSION} · Python {sys.version.split()[0]} · {sys.platform}")
    print(f"Desktop: {os.environ.get('XDG_CURRENT_DESKTOP', 'não identificado')}")
    print(f"Configuração: {config_path()}")
    print(f"Dados: {data_dir()}")
    if not found:
        print("[AVISO] Steam não encontrada. Configure steam_dir se ela estiver em outro local.")
    for index, path in enumerate(found):
        log = path / "logs/shader_log.txt"
        print(f"{'[SELECIONADA]' if index == 0 else '[ALTERNATIVA]'} {path}")
        print(f"  Log: {'legível' if os.access(log, os.R_OK) else 'ausente ou sem permissão de leitura'}")
    if len(found) > 1:
        print("[AVISO] Mais de uma Steam encontrada; fixe steam_dir para escolher outra instalação.")
    print("Inicialização disponível: " + ("systemd de usuário" if systemd_available() else "autostart XDG"))
    print("Notificações: " + ("notify-send disponível" if which("notify-send") else
                              "instale libnotify-bin (Debian/Ubuntu) ou libnotify (Fedora/Arch)"))
    print("Painel GNOME: " + ("versão suportada" if gnome_supported() else
                              "indisponível nesta sessão; use notificações e terminal"))
    try:
        snapshot = read_status(data_dir())
        print(f"[OK] Estado recente do monitor: {snapshot['status']}")
    except ValueError as error:
        print(f"[AVISO] {error}")


def stop_monitor(directory):
    """Para só o processo dono do lock, conferindo identidade antes do sinal."""
    try:
        lock = (directory / "monitor.lock").open("r", encoding="utf-8")
    except FileNotFoundError:
        return False
    with lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
        except BlockingIOError:
            pass
        try:
            owner = json.load(lock)
            pid = int(owner["pid"])
            if pid <= 1:
                raise ValueError("PID inválido")
            process = Path("/proc") / str(pid)
            # Abre antes de verificar: pidfd mantém a identidade mesmo se o PID for reutilizado.
            descriptor = os.pidfd_open(pid) if hasattr(os, "pidfd_open") else None
            try:
                started = (process / "stat").read_text().rsplit(")", 1)[1].split()[19]
                args = (process / "cmdline").read_bytes().split(b"\0")
                package = Path(__file__).resolve().parent
                roots = {package.parent, Path.home() / ".local/lib" / APP_ID}
                scripts = {os.fsencode(root / name) for root in roots
                           for name in ("run.py", "cli.py", "monitor.py")}
                # Também aceita invocação relativa feita diretamente no repositório.
                cwd = (process / "cwd").resolve()
                arg_paths = {os.fsencode((cwd / os.fsdecode(arg)).resolve()) for arg in args[1:] if arg}
                module_matches = (args[1:3] == [b"-m", b"steam_shaders"] and
                                  (cwd / "steam_shaders").resolve() in
                                  {root / "steam_shaders" for root in roots})
                if (process.stat().st_uid != os.getuid() or started != owner["started"] or
                        not (scripts.intersection(arg_paths) or module_matches)):
                    raise ValueError("a identidade do processo não corresponde ao monitor")
                if descriptor is not None and hasattr(signal, "pidfd_send_signal"):
                    signal.pidfd_send_signal(descriptor, signal.SIGTERM)
                else:
                    os.kill(pid, signal.SIGTERM)
            finally:
                if descriptor is not None:
                    os.close(descriptor)
        except ProcessLookupError:
            return False
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise ValueError(f"Não foi possível parar o monitor com segurança: {error}") from error
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except BlockingIOError:
                time.sleep(0.1)
        raise ValueError("O monitor ainda não encerrou. Confira o serviço antes de remover os arquivos.")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Mantém os argumentos do monitor disponíveis sem duplicar seu parser.
    if argv and argv[0] == "run":
        from . import monitor
        monitor.main(argv[1:])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run", help="Acompanha os shaders em primeiro plano")
    show = commands.add_parser("status", help="Mostra o estado recente do monitor")
    show.add_argument("--json", action="store_true", help="Imprime o estado para outras interfaces")
    show.add_argument("--data-dir", type=Path, default=data_dir())
    commands.add_parser("doctor", help="Confere caminhos e recursos do sistema")
    stop = commands.add_parser("stop", help="Para o monitor atual sem apagar seus dados")
    stop.add_argument("--data-dir", type=Path, default=data_dir())
    remove = commands.add_parser("uninstall", help="Remove o programa e preserva os dados")
    remove.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            status(args)
        elif args.command == "doctor":
            doctor()
        elif args.command == "stop":
            print("Monitor encerrado." if stop_monitor(args.data_dir) else "O monitor já está parado.")
        elif args.command == "uninstall":
            from . import installer
            installer.main(["--uninstall", *(["--yes"] if args.yes else [])])
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
