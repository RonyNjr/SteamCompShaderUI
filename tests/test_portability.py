import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from steam_shaders.cli import read_status, stop_monitor
from steam_shaders.installer import install, locations, uninstall
from steam_shaders.monitor import Processes, inspect_processes
from steam_shaders.support import config_path, discover_steam, load_config, steam_candidates, xdg_home

ROOT = Path(__file__).resolve().parents[1]


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "user"
        self.home.mkdir()
        self.home_patch = patch("pathlib.Path.home", return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)
        self.environment = patch.dict(os.environ, {"XDG_DATA_HOME": "", "XDG_CONFIG_HOME": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_flatpak_discovery_without_native_steam(self):
        flatpak = self.home / ".var/app/com.valvesoftware.Steam/.local/share/Steam"
        (flatpak / "logs").mkdir(parents=True)
        self.assertEqual(discover_steam(), [flatpak])

    def test_aliases_are_deduplicated_and_recent_log_wins(self):
        native = self.home / ".local/share/Steam"
        flatpak = self.home / ".var/app/com.valvesoftware.Steam/.local/share/Steam"
        for path, stamp in ((native, 100), (flatpak, 200)):
            (path / "logs").mkdir(parents=True)
            log = path / "logs/shader_log.txt"
            log.touch()
            os.utime(log, (stamp, stamp))
        (self.home / ".steam").mkdir()
        (self.home / ".steam/steam").symlink_to(native)
        (self.home / ".steam/root").symlink_to(native)
        self.assertEqual(discover_steam(), [flatpak, native])
        self.assertEqual(steam_candidates().count(native), 1)

    def test_empty_and_relative_xdg_values_use_default(self):
        for value in ("", "relative/path"):
            with self.subTest(value=value), patch.dict(os.environ, {"XDG_DATA_HOME": value}):
                self.assertEqual(xdg_home("XDG_DATA_HOME", ".local/share"), self.home / ".local/share")

    def test_custom_xdg_data_home_does_not_hide_native_default(self):
        native = self.home / ".local/share/Steam"
        (native / "steamapps").mkdir(parents=True)
        with patch.dict(os.environ, {"XDG_DATA_HOME": str(self.root / "custom")}):
            self.assertEqual(discover_steam(), [native])

    def test_config_validation_and_custom_path(self):
        self.assertEqual(load_config(), {})
        config_path().parent.mkdir(parents=True)
        for invalid in ([], {"steam_dir": "relative"}, {"notifications": "no"}):
            config_path().write_text(json.dumps(invalid))
            with self.assertRaises(ValueError):
                load_config()
        expected = {"steam_dir": str(self.root / "Steam"), "notifications": False}
        config_path().write_text(json.dumps(expected))
        self.assertEqual(load_config(), expected)


class InstallerTests(unittest.TestCase):
    def test_autostart_and_uninstall_preserve_user_data(self):
        with tempfile.TemporaryDirectory(prefix="steam shaders '\"$%\\") as folder, contextlib.redirect_stdout(io.StringIO()):
            root = Path(folder)
            paths = install(root, startup="autostart", gnome="no")
            self.assertFalse((root / "config/systemd/user/steam-shaders.service").exists())
            self.assertFalse((root / "share/gnome-shell/extensions").exists())
            desktop = root / "config/autostart/steam-shaders.desktop"
            if shutil.which("desktop-file-validate"):
                subprocess.run(["desktop-file-validate", str(desktop)], check=True, capture_output=True)
            version = subprocess.check_output([str(paths["bin"]), "--version"], text=True).strip()
            self.assertEqual(version, "0.2.0")
            diagnostic = subprocess.run([str(paths["bin"]), "doctor"],
                                        capture_output=True, text=True, timeout=10)
            self.assertEqual(diagnostic.returncode, 0, diagnostic.stderr)
            state = root / "share/steamcompshaderui"
            state.mkdir(parents=True)
            (state / "history.sqlite3").write_bytes(b"preserve")
            unrelated = paths["lib"] / "user-note.txt"
            unrelated.write_text("preserve")
            uninstall(root)
            self.assertEqual((state / "history.sqlite3").read_bytes(), b"preserve")
            self.assertTrue(unrelated.exists())
            self.assertFalse(paths["bin"].exists())
            self.assertFalse(desktop.exists())

    def test_systemd_then_none_removes_old_startup_files(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            root = Path(folder)
            install(root, startup="systemd", gnome="no")
            install(root, startup="none", gnome="no")
            self.assertFalse((root / "config/systemd/user/steam-shaders.service").exists())
            self.assertFalse((root / "config/autostart/steam-shaders.desktop").exists())

    def test_upgrade_moves_managed_code_into_package_without_removing_user_files(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            root = Path(folder)
            library = root / "lib/steamcompshaderui"
            library.mkdir(parents=True)
            for name in ("cli.py", "monitor.py", "support.py", "install.py"):
                (library / name).write_text("# managed legacy file\n")
            (library / "user-note.txt").write_text("preserve")
            install(root, startup="none", gnome="no")
            self.assertTrue((library / "steam_shaders/cli.py").exists())
            self.assertTrue((library / "run.py").exists())
            self.assertFalse((library / "cli.py").exists())
            self.assertFalse((library / "monitor.py").exists())
            self.assertEqual((library / "user-note.txt").read_text(), "preserve")

    def test_auto_without_systemd_or_gnome_has_no_gnome_dependency(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            with patch("steam_shaders.installer.locations", return_value=locations(folder)), \
                    patch("steam_shaders.installer.systemd_available", return_value=False), \
                    patch("steam_shaders.installer.gnome_supported", return_value=False):
                result = install()
            self.assertEqual(result["startup"], "autostart")
            self.assertFalse(result["gnome"])


class RuntimeTests(unittest.TestCase):
    def test_unavailable_proc_is_not_a_crash(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(inspect_processes(Path(folder) / "missing"), Processes())

    def test_other_users_processes_are_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            process = root / "42"
            process.mkdir()
            (process / "comm").write_text("fossilize_replay")
            (process / "cmdline").write_bytes(b"/bin/fossilize_replay\0")
            with patch("steam_shaders.monitor.os.getuid", return_value=os.getuid() + 1):
                self.assertFalse(inspect_processes(root).replay)

    def test_stale_status_and_stopped_status_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            for state in ({"version": 1, "updated_at": time.time() - 30},
                          {"version": 1, "updated_at": time.time(), "monitor_stopped": True}):
                (directory / "status.json").write_text(json.dumps(state))
                with self.assertRaises(ValueError):
                    read_status(directory)

    def test_monitor_lifecycle_duplicate_lock_status_and_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            steam, state = directory / "Steam Flatpak", directory / "state"
            (steam / "logs").mkdir(parents=True)
            (steam / "logs/shader_log.txt").write_text("")
            environment = dict(os.environ, XDG_CONFIG_HOME=str(directory / "config"))
            args = [sys.executable, "-m", "steam_shaders", "run", "--steam-dir", str(steam),
                    "--data-dir", str(state), "--no-notifications"]
            process = subprocess.Popen(args, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 5
                while not (state / "status.json").exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                snapshot = read_status(state)
                self.assertEqual(snapshot["steam_dir"], str(steam))
                self.assertEqual(snapshot["status"], "idle")
                owner = (state / "monitor.lock").read_text()
                duplicate = subprocess.run(args, env=environment, capture_output=True, text=True, timeout=5)
                self.assertNotEqual(duplicate.returncode, 0)
                self.assertIn("já está em execução", duplicate.stderr)
                self.assertEqual((state / "monitor.lock").read_text(), owner)
                self.assertTrue(stop_monitor(state))
                process.wait(timeout=5)
                self.assertEqual(process.returncode, 0)
                self.assertTrue(json.loads((state / "status.json").read_text())["monitor_stopped"])
                self.assertFalse(stop_monitor(state))
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
                process.stderr.close()


if __name__ == "__main__":
    unittest.main()
