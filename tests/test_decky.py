"""Testa o backend real com a API do Decky simulada e logs temporários."""

import asyncio
import importlib.util
import json
import logging
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from scripts.bundle_backend import bundle

ROOT = Path(__file__).resolve().parents[1]


class DeckyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        bundle()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.steam = self.root / "Steam"
        (self.steam / "logs").mkdir(parents=True)
        self.log = self.steam / "logs/shader_log.txt"
        self.log.write_text("")
        self.settings = self.root / "settings"
        self.settings.mkdir()
        (self.settings / "config.json").write_text(json.dumps({"steam_dir": str(self.steam)}))
        self.api = SimpleNamespace(DECKY_PLUGIN_RUNTIME_DIR=str(self.root / "runtime"),
                                   DECKY_PLUGIN_SETTINGS_DIR=str(self.settings),
                                   emit=AsyncMock(), logger=logging.getLogger("decky-test"))
        with patch.dict(sys.modules, {"decky": self.api}):
            spec = importlib.util.spec_from_file_location("steam_shaders_decky_test", ROOT / "main.py")
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)
            self.monitor = sys.modules["steam_shaders.monitor"]
        self.plugin = self.module.Plugin()
        self.process_patch = patch.object(self.monitor, "inspect_processes", return_value=self.monitor.Processes(steam=True))
        self.process_patch.start()
        self.addCleanup(self.process_patch.stop)

    async def asyncTearDown(self):
        await self.plugin._unload()

    async def wait_for(self, predicate):
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            if predicate():
                return
            await asyncio.sleep(0.05)
        self.fail("O backend não chegou ao estado esperado")

    async def test_lifecycle_live_completion_event_and_persistent_history(self):
        with patch.object(self.monitor, "COMPLETION_DELAY", 0):
            await self.plugin._main()
            state_path = self.root / "runtime/status.json"
            await self.wait_for(state_path.exists)
            self.assertEqual((await self.plugin.get_status())["status"], "idle")
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            self.log.write_text(
                f"[{stamp}] Starting processing job for app 42!\n"
                f"[{stamp}] [ App ID 42 ] fossilize_replay completed, remove from build queue.\n")
            await self.wait_for(lambda: self.api.emit.await_count > 0)
            self.api.emit.assert_awaited_once_with("shaders_completed", "AppID 42")
            state = await self.plugin.get_status()
            self.assertEqual(state["recent"][0]["outcome"], "completed")
            await self.plugin._unload()
            self.assertTrue((self.root / "runtime/history.sqlite3").exists())
            self.assertIsNotNone((await self.plugin.get_status()).get("error"))
            await self.plugin._uninstall()
            self.assertTrue((self.root / "runtime/history.sqlite3").exists())

    async def test_invalid_settings_report_failure_and_release_lock(self):
        (self.settings / "config.json").write_text('{"steam_dir": "relative"}')
        with self.assertLogs("decky-test", level="ERROR"):
            await self.plugin._main()
            await self.wait_for(lambda: self.plugin._task.done())
        self.assertIsNotNone((await self.plugin.get_status()).get("error"))

    async def test_stale_state_is_not_presented_as_active(self):
        await self.plugin._main()
        await self.wait_for((self.root / "runtime/status.json").exists)
        await self.plugin._unload()
        (self.root / "runtime/status.json").write_text(json.dumps({
            "version": 1, "updated_at": time.time() - 60, "status": "compiling", "active": {"name": "old"},
        }))
        state = await self.plugin.get_status()
        self.assertIsNone(state["active"])
        self.assertIsNotNone(state.get("error"))


if __name__ == "__main__":
    unittest.main()
