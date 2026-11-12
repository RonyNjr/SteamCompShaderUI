"""Backend do Decky: executa o mesmo monitor, sem systemd nem processos auxiliares."""

import asyncio
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import decky

from .monitor import run


class Plugin:
    async def _main(self):
        self._stop = threading.Event()
        self._error = None
        self._directory = Path(decky.DECKY_PLUGIN_RUNTIME_DIR)
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(asyncio.to_thread(self._worker))

    def _worker(self):
        settings = Path(decky.DECKY_PLUGIN_SETTINGS_DIR) / "config.json"
        try:
            config = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
            if not isinstance(config, dict):
                raise ValueError("A configuração do plugin deve ser um objeto JSON.")
            steam = config.get("steam_dir")
            if steam is not None and (not isinstance(steam, str) or not Path(steam).is_absolute()):
                raise ValueError("steam_dir deve ser um caminho absoluto.")
            if "notifications" in config and not isinstance(config["notifications"], bool):
                raise ValueError("notifications deve ser true ou false.")
            self._notifications = config.get("notifications", True)
            args = SimpleNamespace(data_dir=self._directory, steam_dir=Path(steam) if steam else None,
                                   once=False, no_notifications=True)
            run(args, stop_event=self._stop, on_notification=self._completed,
                register_signals=False)
        except (Exception, SystemExit) as error:
            self._error = str(error)
            decky.logger.exception("Steam Shaders: falha no monitor")

    def _completed(self, row, names):
        if not self._notifications or self._stop.is_set():
            return
        name = names.get(row["appid"])
        future = asyncio.run_coroutine_threadsafe(decky.emit("shaders_completed", name), self._loop)
        # Consome falhas de emissão sem interromper a leitura do log.
        def emitted(result):
            try:
                result.result()
            except Exception:
                decky.logger.exception("Steam Shaders: falha na notificação")
        future.add_done_callback(emitted)

    async def get_status(self):
        return await asyncio.to_thread(self._read_status)

    def _read_status(self):
        empty = {"version": 1, "updated_at": time.time(), "status": "idle", "active": None, "recent": []}
        if getattr(self, "_error", None):
            return dict(empty, error="O monitor parou. Confira o log do plugin no Decky.")
        try:
            state = json.loads((self._directory / "status.json").read_text(encoding="utf-8"))
            if not isinstance(state, dict) or state.get("version") != 1:
                raise ValueError("Estado incompatível")
            if state.get("monitor_stopped") or not -5 <= time.time() - state["updated_at"] <= 20:
                raise ValueError("Estado desatualizado")
            return state
        except FileNotFoundError:
            return empty
        except (OSError, ValueError, TypeError, KeyError):
            return dict(empty, error="O estado do monitor está indisponível. Recarregue o plugin.")

    async def _unload(self):
        if hasattr(self, "_stop"):
            self._stop.set()
        task = getattr(self, "_task", None)
        if task:
            await asyncio.wait_for(asyncio.shield(task), timeout=10)

    async def _uninstall(self):
        # O Decky controla seus diretórios; o plugin não apaga o histórico do usuário.
        await self._unload()
