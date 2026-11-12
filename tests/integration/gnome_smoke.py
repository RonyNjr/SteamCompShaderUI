#!/usr/bin/env python3
"""Teste opcional no GNOME headless, com D-Bus e diretórios XDG isolados."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from steam_shaders.installer import install


PROBE = r'''
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

export default class Probe extends Extension {
    enable() {
        this._stage = 0;
        this._results = [];
        this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 1, () => {
            const target = Extension.lookupByUUID('steam-shaders@rony.local');
            const indicator = Main.panel.statusArea['steam-shaders@rony.local'];
            if (!indicator || !target)
                return GLib.SOURCE_CONTINUE;
            if (this._stage === 0 && indicator.visible && target._label.text === '62%') {
                this._results.push('compiling-visible-62%');
                indicator.menu.open({animate: false});
                this._stage = 1;
            } else if (this._stage === 1) {
                this._stage = 2;
                this._capture().finally(() => this._writeStatus('finishing'));
            } else if (this._stage === 2 && indicator.visible && target._label.text === '…') {
                this._results.push('finishing-visible');
                this._stage = 3;
                this._writeStatus('idle');
            } else if (this._stage === 3 && !indicator.visible) {
                this._results.push('idle-hidden');
                GLib.file_set_contents(`${GLib.get_user_data_dir()}/result.json`,
                    JSON.stringify(this._results));
                this._timer = 0;
                return GLib.SOURCE_REMOVE;
            }
            return GLib.SOURCE_CONTINUE;
        });
    }
    async _capture() {
        try {
            Gio._promisify(Shell.Screenshot.prototype, 'screenshot_area', 'screenshot_area_finish');
            const shooter = new Shell.Screenshot();
            const file = Gio.File.new_for_path(`${GLib.get_user_data_dir()}/preview.png`);
            const stream = file.replace(null, false, Gio.FileCreateFlags.NONE, null);
            try {
                await shooter.screenshot_area(880, 0, 400, 330, stream);
            } finally {
                stream.close(null);
            }
        } catch (error) {
            GLib.file_set_contents(`${GLib.get_user_data_dir()}/screenshot-error.txt`, error.message);
        }
    }
    _writeStatus(status) {
        const file = Gio.File.new_for_path(`${GLib.get_user_data_dir()}/steamcompshaderui/status.json`);
        const [, bytes] = file.load_contents(null);
        const data = JSON.parse(new TextDecoder().decode(bytes));
        data.status = status;
        data.updated_at = Date.now() / 1000;
        GLib.file_set_contents(file.get_path(), JSON.stringify(data));
    }
    disable() {
        if (this._timer)
            GLib.source_remove(this._timer);
        this._timer = 0;
    }
}
'''


def inner(root):
    share = root / "share"
    subprocess.run(["gsettings", "set", "org.gnome.shell", "enabled-extensions",
                    "['steam-shaders@rony.local', 'probe@steam-shaders.test']"], check=True)
    subprocess.run(["gsettings", "set", "org.gnome.shell", "welcome-dialog-last-shown-version", "999"],
                   capture_output=True)
    state = share / "steamcompshaderui/status.json"
    state.write_text(json.dumps({
        "version": 1, "updated_at": time.time(), "status": "compiling", "recent": [],
        "active": {"name": "Jogo de exemplo ®", "percent": 62, "stage": 2, "done": 3213829,
                   "total": 3623167, "elapsed_seconds": 7200, "eta_seconds": 682,
                   "rate": 600, "start_known": True, "stale": False, "cycles": 1},
    }))
    with (root / "shell.log").open("w") as log:
        shell = subprocess.Popen(["gnome-shell", "--headless", "--wayland",
                                  "--virtual-monitor=1280x720", "--no-x11"],
                                 stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline and shell.poll() is None:
                if (share / "result.json").exists():
                    break
                time.sleep(0.5)
            result = json.loads((share / "result.json").read_text())
            assert result == ["compiling-visible-62%", "finishing-visible", "idle-hidden"], result
            print("GNOME 51: compilação, menu, confirmação e ocultação passaram.", flush=True)
        finally:
            shell.terminate()
            try:
                shell.wait(timeout=8)
            except subprocess.TimeoutExpired:
                shell.kill()
                shell.wait()
    errors = [line for line in (root / "shell.log").read_text().splitlines() if "JS ERROR" in line]
    assert not errors, "\n".join(errors)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--inner":
        inner(Path(sys.argv[2]))
        return
    root = Path(tempfile.mkdtemp(prefix="steam-shaders-gnome-"))
    install(root)
    (root / "runtime").mkdir(mode=0o700)
    (root / "share/steamcompshaderui").mkdir()
    probe = root / "share/gnome-shell/extensions/probe@steam-shaders.test"
    probe.mkdir()
    (probe / "metadata.json").write_text(json.dumps({
        "uuid": "probe@steam-shaders.test", "name": "Teste isolado", "description": "Teste",
        "shell-version": ["51"],
    }))
    (probe / "extension.js").write_text(PROBE)
    env = dict(os.environ, XDG_DATA_HOME=str(root / "share"), XDG_CONFIG_HOME=str(root / "config"),
               XDG_CACHE_HOME=str(root / "cache"), XDG_RUNTIME_DIR=str(root / "runtime"),
               GSETTINGS_BACKEND="keyfile", LIBGL_ALWAYS_SOFTWARE="1")
    with (root / "session.log").open("w") as log:
        result = subprocess.run(["dbus-run-session", "--", sys.executable, __file__, "--inner", str(root)],
                                env=env, stdout=log, stderr=subprocess.STDOUT, timeout=55)
    print((root / "session.log").read_text()[-2500:])
    print(f"Artefatos da sessão isolada: {root}")
    if result.returncode:
        print((root / "shell.log").read_text()[-6000:])
        raise SystemExit(result.returncode)
    if (root / "share/screenshot-error.txt").exists():
        print("Captura: " + (root / "share/screenshot-error.txt").read_text())
    elif (root / "share/preview.png").exists():
        print(f"Prévia com dados simulados: {root / 'share/preview.png'}")


if __name__ == "__main__":
    main()
