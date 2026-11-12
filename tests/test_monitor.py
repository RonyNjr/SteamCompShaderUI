import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest
from unittest.mock import patch

from steam_shaders.installer import configure_next_login, install, unit_quote
from steam_shaders.monitor import (GameNames, History, LogFollower, Processes, Tracker,
                     atomic_json, inspect_processes, parse_event, read_vdf)


class Names:
    def get(self, appid):
        return f"Jogo {appid}"


def event(kind, stamp=1000, appid="123", **values):
    return {"kind": kind, "at": stamp, "appid": appid, **values}


def progress(stamp, percent, done, total=1000, appid="123"):
    return event("progress", stamp, appid, percent=percent, done=done, total=total)


class ParsingTests(unittest.TestCase):
    def test_real_log_lines(self):
        lines = [
            ("Starting processing job for app 123!", "start"),
            ("Still replaying 123 (62%, 3213829/3623167).", "progress"),
            ("[ App ID 123 ] fossilize_replay completed, remove from build queue.", "complete"),
            ("Destroyed compile job 123.", "destroy"),
            ("Destroyed compile job 123", "destroy"),
        ]
        for text, kind in lines:
            with self.subTest(text=text):
                parsed = parse_event(f"[2026-11-09 13:13:38] {text}\r\n")
                self.assertEqual(parsed["kind"], kind)
                self.assertEqual(parsed["appid"], "123")
        self.assertIsNone(parse_event("[2026-11-09 13:13:38] Mismatching key! Entry 1234."))
        self.assertIsNone(parse_event("[invalid] Starting processing job for app 1!"))

    def test_vdf_quotes_unicode_empty_and_comments(self):
        parsed = read_vdf(r'''// comentário
"AppState" { "name" "Jogo \"Especial\" ®" "empty" "" "nested" { "key" "value" } }
''')
        self.assertEqual(parsed["AppState"]["name"], 'Jogo "Especial" ®')
        self.assertEqual(parsed["AppState"]["empty"], "")
        self.assertEqual(parsed["AppState"]["nested"]["key"], "value")

    def test_names_in_second_library(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            steam, library = root / "steam", root / "HD jogos"
            (steam / "steamapps").mkdir(parents=True)
            (library / "steamapps").mkdir(parents=True)
            (steam / "steamapps/libraryfolders.vdf").write_text(
                f'"libraryfolders" {{ "1" {{ "path" "{library}" }} }}')
            (library / "steamapps/appmanifest_42.acf").write_text(
                '"AppState" { "appid" "42" "name" "Jogo no HD ®" }')
            names = GameNames(steam)
            self.assertEqual(names.get("42"), "Jogo no HD ®")
            self.assertEqual(names.get("99"), "AppID 99")
            self.assertEqual(names.get(None), "Jogo não identificado")


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.tracker = Tracker()

    def test_eta_recalculated_when_total_changes(self):
        self.tracker.feed(progress(1000, 40, 100))
        self.tracker.feed(progress(1010, 45, 200))
        data = self.tracker.snapshot(1010, Names())["active"]
        self.assertEqual(data["rate"], 10)
        self.assertEqual(data["eta_seconds"], 80)
        self.tracker.feed(progress(1020, 43, 300, 2000))
        data = self.tracker.snapshot(1020, Names())["active"]
        self.assertEqual(data["rate"], 10)
        self.assertEqual(data["eta_seconds"], 170)

    def test_reset_samples_on_stage_or_counter_reset(self):
        self.tracker.feed(progress(1000, 60, 800))
        self.tracker.feed(progress(1010, 65, 900))
        self.tracker.feed(progress(1020, 66, 0, 200))
        data = self.tracker.snapshot(1020, Names())["active"]
        self.assertEqual(data["stage"], 3)
        self.assertIsNone(data["eta_seconds"])
        self.tracker.feed(progress(1030, 70, 50, 200))
        self.assertEqual(self.tracker.snapshot(1030, Names())["active"]["eta_seconds"], 30)
        self.tracker.feed(progress(1040, 68, 20, 200))
        self.assertIsNone(self.tracker.snapshot(1040, Names())["active"]["rate"])

    def test_12_seconds_without_log_does_not_complete(self):
        self.tracker.feed(progress(1000, 62, 100))
        self.tracker.tick(1012, Processes(steam=True))
        self.assertIsNotNone(self.tracker.active)
        self.assertFalse(self.tracker.notifications)

    def test_stale_log_with_live_process_keeps_indicator_without_eta(self):
        self.tracker.feed(progress(1000, 40, 100))
        self.tracker.feed(progress(1010, 45, 200))
        self.tracker.tick(1100, Processes(steam=True, replay=True, appids={"123"}))
        data = self.tracker.snapshot(1100, Names())
        self.assertEqual(data["status"], "compiling")
        self.assertTrue(data["active"]["stale"])
        self.assertIsNone(data["active"]["eta_seconds"])

    def test_same_second_restart_coalesces_completion(self):
        self.tracker.feed(event("start"))
        self.tracker.feed(event("complete", 1020))
        self.tracker.feed(event("destroy", 1020))
        self.tracker.feed(event("start", 1020))
        self.tracker.tick(1040, Processes(steam=True, replay=True))
        self.assertEqual(self.tracker.active["cycles"], 2)
        self.assertFalse(self.tracker.notifications)
        self.assertFalse(self.tracker.finished)
        self.tracker.feed(event("complete", 1100))
        self.tracker.tick(1114, Processes(steam=True))
        self.assertFalse(self.tracker.notifications)
        self.tracker.tick(1115, Processes(steam=True))
        self.assertEqual(len(self.tracker.notifications), 1)
        self.assertEqual(self.tracker.finished[0]["started_at"], 1000)

    def test_other_game_completion_never_finishes_active_game(self):
        self.tracker.feed(event("start"))
        self.tracker.feed(event("complete", 1010, "42"))
        self.tracker.tick(1025, Processes(steam=True, replay=True, appids={"123"}))
        self.assertEqual(self.tracker.active["appid"], "123")
        self.assertEqual(self.tracker.notifications[0]["appid"], "42")

    def test_short_restart_can_also_complete_in_the_same_second(self):
        self.tracker.feed(event("start"))
        self.tracker.feed(event("complete", 1020))
        self.tracker.feed(event("start", 1020))
        self.tracker.feed(event("complete", 1020))
        self.tracker.feed(event("destroy", 1020))
        self.tracker.tick(1035, Processes(steam=True))
        self.assertEqual(len(self.tracker.notifications), 1)
        self.assertEqual(self.tracker.finished[0]["outcome"], "completed")
        self.assertEqual(self.tracker.finished[0]["cycles"], 2)

    def test_next_game_can_compile_while_previous_completion_waits(self):
        self.tracker.feed(event("start"))
        self.tracker.feed(event("complete", 1010))
        self.tracker.feed(event("start", 1010, "42"))
        self.tracker.tick(1025, Processes(steam=True, replay=True))
        self.assertEqual(self.tracker.active["appid"], "42")
        self.assertEqual(self.tracker.notifications[0]["appid"], "123")

    def test_destroy_without_completion_is_interrupted(self):
        self.tracker.feed(event("start"))
        self.tracker.feed(event("destroy", 1020))
        self.assertIsNone(self.tracker.active)
        self.assertEqual(self.tracker.finished[0]["outcome"], "interrupted")
        self.assertFalse(self.tracker.notifications)

    def test_process_disappearance_does_not_claim_success(self):
        self.tracker.feed(event("start"))
        self.tracker.tick(1046, Processes(steam=True))
        self.assertIsNone(self.tracker.active)
        self.assertEqual(self.tracker.finished[0]["outcome"], "interrupted")
        self.assertFalse(self.tracker.notifications)

    def test_steam_exit_is_interrupted(self):
        self.tracker.feed(event("start"))
        self.tracker.tick(1011, Processes())
        self.assertEqual(self.tracker.finished[0]["outcome"], "interrupted")
        self.assertFalse(self.tracker.notifications)

    def test_old_log_does_not_notify_at_boot(self):
        self.tracker.feed(event("start"), live=False)
        self.tracker.feed(event("complete", 1010), live=False)
        self.tracker.tick(1025, Processes(steam=True))
        self.assertFalse(self.tracker.notifications)
        self.assertEqual(self.tracker.finished[0]["outcome"], "completed")

    def test_pending_completion_survives_monitor_restart(self):
        self.tracker.feed(event("start"))
        self.tracker.feed(event("complete", 1010))
        restored = Tracker(json.loads(json.dumps(self.tracker.checkpoint())))
        restored.tick(1025, Processes(steam=True))
        self.assertEqual(len(restored.notifications), 1)

    def test_replayed_log_does_not_duplicate_history(self):
        self.tracker.feed(event("start"))
        self.tracker.feed(event("complete", 1010))
        self.tracker.tick(1025, Processes(steam=True))
        restored = Tracker(self.tracker.checkpoint())
        restored.feed(event("start"))
        restored.feed(event("complete", 1010))
        restored.tick(1030, Processes(steam=True))
        self.assertFalse(restored.finished)
        self.assertFalse(restored.notifications)

    def test_process_can_recover_activity_when_log_is_gone(self):
        self.tracker.tick(1000, Processes(steam=True, replay=True, appids={"42"}))
        active = self.tracker.snapshot(1000, Names())["active"]
        self.assertEqual(active["appid"], "42")
        self.assertFalse(active["start_known"])
        self.assertIsNone(active["percent"])

    def test_unknown_process_is_identified_without_false_interruption(self):
        self.tracker.tick(1000, Processes(steam=True, replay=True))
        self.tracker.feed(progress(1010, 62, 100))
        self.assertEqual(self.tracker.active["appid"], "123")
        self.assertFalse(self.tracker.finished)

    def test_recovered_sessions_have_stable_ids_for_history(self):
        self.assertEqual(Tracker.new_job("42", 1000)["id"], Tracker.new_job("42", 1000)["id"])


LINE1 = b"[2026-11-09 13:13:38] Starting processing job for app 42!\n"
LINE2 = b"[2026-11-09 13:13:48] Still replaying 42 (45%, 100/1000).\n"
LINE3 = b"[2026-11-09 13:13:58] Still replaying 42 (50%, 200/1000).\n"


class FollowerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "shader_log.txt"
        self.path.write_bytes(LINE1)
        self.follower = LogFollower(self.path)
        self.addCleanup(self.follower.close)

    def test_incremental_reads_and_partial_lines(self):
        self.assertEqual(len(self.follower.poll()), 1)
        self.assertEqual(self.follower.poll(), [])
        with self.path.open("ab") as log:
            log.write(LINE2[:-5])
        self.assertEqual(self.follower.poll(), [])
        cursor = self.follower.cursor()
        self.assertEqual(cursor["offset"], len(LINE1))
        with self.path.open("ab") as log:
            log.write(LINE2[-5:])
        self.assertEqual(len(self.follower.poll()), 1)
        self.assertEqual(self.follower.poll(), [])

    def test_resumes_at_cursor_including_partial_line(self):
        with self.path.open("ab") as log:
            log.write(LINE2[:-5])
        self.follower.poll()
        cursor = self.follower.cursor()
        self.follower.close()
        with self.path.open("ab") as log:
            log.write(LINE2[-5:])
        restored = LogFollower(self.path, cursor)
        self.addCleanup(restored.close)
        lines = restored.poll()
        self.assertEqual(len(lines), 1)
        self.assertIn("45%", lines[0])

    def test_rotation_drains_old_descriptor_then_new_file(self):
        self.follower.poll()
        with self.path.open("ab") as log:
            log.write(LINE2)
        self.path.rename(self.path.with_name("shader_log.previous.txt"))
        self.path.write_bytes(LINE3)
        lines = self.follower.poll()
        self.assertEqual([parse_event(line)["done"] for line in lines], [100, 200])

    def test_double_rotation_recovers_deleted_open_file(self):
        self.follower.poll()
        with self.path.open("ab") as log:
            log.write(LINE2)
        previous = self.path.with_name("shader_log.previous.txt")
        self.path.rename(previous)
        self.path.write_bytes(LINE3)
        self.path.replace(previous)
        self.path.write_bytes(b"noise\n")
        lines = self.follower.poll()
        self.assertEqual([parse_event(line)["done"] for line in lines], [100, 200])

    def test_restart_after_rotation_finds_cursor_in_previous(self):
        self.follower.poll()
        cursor = self.follower.cursor()
        self.follower.close()
        with self.path.open("ab") as log:
            log.write(LINE2)
        self.path.rename(self.path.with_name("shader_log.previous.txt"))
        self.path.write_bytes(LINE3)
        restored = LogFollower(self.path, cursor)
        self.addCleanup(restored.close)
        self.assertEqual([parse_event(line)["done"] for line in restored.poll()], [100, 200])

    def test_truncate_and_rewrite_beyond_old_cursor(self):
        self.follower.poll()
        self.path.write_bytes(b"noise\n" * 30 + LINE2)
        lines = self.follower.poll()
        self.assertEqual(len(lines), 1)
        self.assertEqual(parse_event(lines[0])["done"], 100)

    def test_missing_log_then_created(self):
        self.path.unlink()
        self.assertEqual(self.follower.poll(), [])
        self.path.write_bytes(LINE1)
        self.assertEqual(len(self.follower.poll()), 1)


class PersistenceAndProcessTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("gjs") and shutil.which("gsettings"), "Requer GJS e schemas do GNOME")
    def test_next_login_registration_persists_in_isolated_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": folder, "GSETTINGS_BACKEND": "keyfile"}):
                configure_next_login()
                configured = subprocess.check_output(
                    ["gsettings", "get", "org.gnome.shell", "enabled-extensions"], text=True)
            self.assertIn("steam-shaders@rony.local", configured)

    def test_sqlite_session_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            history = History(Path(folder) / "history.sqlite3")
            self.addCleanup(history.close)
            row = dict(Tracker.new_job("42", 1000), ended_at=1020, outcome="completed")
            history.add(row, Names())
            history.add(row, Names())
            self.assertEqual(len(history.recent()), 1)
            self.assertEqual(history.recent()[0]["name"], "Jogo 42")

    def test_proc_identifies_real_replay_not_unrelated_cmdline(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for pid, comm, cmdline, env in [
                ("1", "steam", b"/path/steam\0", b""),
                ("2", "fossilize_replay", b"/path/fossilize_replay\0", b"SteamAppId=42\0"),
                ("3", "bash", b"bash\0-c\0pgrep fossilize_replay\0", b""),
            ]:
                process = root / pid
                process.mkdir()
                (process / "comm").write_text(comm)
                (process / "cmdline").write_bytes(cmdline)
                (process / "environ").write_bytes(env)
            found = inspect_processes(root)
            self.assertTrue(found.steam)
            self.assertTrue(found.replay)
            self.assertEqual(found.appids, {"42"})

    def test_atomic_snapshot_and_staged_install(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            atomic_json(root / "status.json", {"name": "Jogo ®"})
            self.assertEqual(json.loads((root / "status.json").read_text())["name"], "Jogo ®")
            self.assertFalse((root / "status.tmp").exists())
            install(root)
            self.assertTrue((root / "lib/steamcompshaderui/steam_shaders/monitor.py").is_file())
            self.assertTrue((root / "share/gnome-shell/extensions/steam-shaders@rony.local/extension.js").is_file())
            unit = (root / "config/systemd/user/steam-shaders.service").read_text()
            self.assertIn("WantedBy=graphical-session.target", unit)
            self.assertIn("NoNewPrivileges=yes", unit)
            self.assertEqual(unit_quote('/path/with "quotes"/% $'), '"/path/with \\"quotes\\"/%% $$"')


if __name__ == "__main__":
    unittest.main()
