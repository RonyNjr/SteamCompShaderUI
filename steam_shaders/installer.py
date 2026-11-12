#!/usr/bin/env python3
"""Instala, atualiza ou remove o Steam Shaders somente para o usuário atual."""

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

from .support import APP_ID, GNOME_VERSIONS, VERSION, xdg_home

UUID = "steam-shaders@rony.local"
PACKAGE = Path(__file__).resolve().parent
SOURCE = PACKAGE.parent
PROGRAM_FILES = ("__init__.py", "__main__.py", "monitor.py", "support.py", "cli.py",
                 "installer.py", "decky.py")
LEGACY_FILES = ("monitor.py", "support.py", "cli.py", "install.py")
EXTENSION_FILES = ("extension.js", "model.js", "stylesheet.css", "metadata.json",
                   "icons/shader-symbolic.svg")
SERVICE = "steam-shaders.service"


def unit_quote(value):
    value = str(value)
    if "\n" in value or "\r" in value:
        raise ValueError("O caminho de instalação não pode conter quebras de linha.")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$") + '"'


def environment_quote(value):
    # Environment= não expande $, ao contrário de ExecStart=.
    return unit_quote(value).replace("$$", "$")


def desktop_quote(value):
    # Exec tem duas camadas: escapes de string e escapes do argumento entre aspas.
    value = str(value)
    if "\n" in value or "\r" in value:
        raise ValueError("O caminho de instalação não pode conter quebras de linha.")
    value = value.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
    return '"' + value.replace("\\", "\\\\").replace("%", "%%") + '"'


def locations(root=None):
    root = Path(root).expanduser().resolve() if root else None
    return {
        "lib": root / "lib" / APP_ID if root else Path.home() / ".local/lib" / APP_ID,
        "bin": root / "bin/steam-shaders" if root else Path.home() / ".local/bin/steam-shaders",
        "data": root / "share" if root else xdg_home("XDG_DATA_HOME", ".local/share"),
        "config": root / "config" if root else xdg_home("XDG_CONFIG_HOME", ".config"),
    }


def systemd_available():
    if not shutil.which("systemctl"):
        return False
    try:
        return subprocess.run(["systemctl", "--user", "show-environment"],
                              capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def gnome_supported():
    desktops = os.environ.get("XDG_CURRENT_DESKTOP", "").lower().split(":")
    if "gnome" not in desktops or not shutil.which("gnome-shell"):
        return False
    try:
        result = subprocess.run(["gnome-shell", "--version"], text=True,
                                capture_output=True, timeout=5, check=True)
    except (OSError, subprocess.SubprocessError):
        return False
    match = re.search(r"\b(\d+)\.", result.stdout)
    return bool(match and match[1] in GNOME_VERSIONS)


def install(root=None, startup="auto", gnome="auto"):
    paths = locations(root)
    mode = startup
    if mode == "auto":
        mode = "systemd" if root or systemd_available() else "autostart"
    if mode == "systemd" and not root and not systemd_available():
        raise ValueError("systemd de usuário indisponível; use --startup autostart.")
    with_gnome = gnome == "yes" or (gnome == "auto" and (bool(root) or gnome_supported()))
    if gnome == "yes" and not root and not gnome_supported():
        raise ValueError("Esta sessão/versão do GNOME não é suportada pela extensão. Use --gnome no.")
    lib, launcher = paths["lib"], paths["bin"]
    unit_path = paths["config"] / "systemd/user" / SERVICE
    autostart = paths["config"] / "autostart/steam-shaders.desktop"
    command = f"{unit_quote(sys.executable)} {unit_quote(lib / 'run.py')} run"
    desktop_command = ("systemctl --user start " + SERVICE if mode == "systemd" else
                       f"{desktop_quote(sys.executable)} {desktop_quote(lib / 'run.py')} run")
    (lib / "steam_shaders").mkdir(parents=True, exist_ok=True)
    for name in PROGRAM_FILES:
        source, target = PACKAGE / name, lib / "steam_shaders" / name
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
    (lib / "run.py").write_text(
        'from steam_shaders.cli import main\n\nif __name__ == "__main__":\n    main()\n', encoding="utf-8")
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' ' +
                        shlex.quote(str(lib / "run.py")) + ' "$@"\n', encoding="utf-8")
    launcher.chmod(0o755)
    extension = paths["data"] / "gnome-shell/extensions" / UUID
    if with_gnome:
        for name in EXTENSION_FILES:
            destination = extension / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            origin = SOURCE / "integrations" / ("shared" if name == "model.js" else "gnome") / name
            shutil.copy2(origin, destination)
    for name in LEGACY_FILES:
        (lib / name).unlink(missing_ok=True)
    if mode != "systemd" and unit_path.exists():
        if not root and systemd_available():
            subprocess.run(["systemctl", "--user", "disable", "--now", SERVICE], check=True, timeout=20)
        unit_path.unlink()
    if mode == "systemd":
        unit_path.parent.mkdir(parents=True, exist_ok=True)
        # O autostart também inicia a unidade em desktops que não ativam
        # graphical-session.target. systemctl start é idempotente.
        unit_path.write_text(f"""[Unit]
Description=Steam shader compilation monitor
After=graphical-session-pre.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart={command}
Environment={environment_quote('XDG_DATA_HOME=' + str(paths['data']))}
Environment={environment_quote('XDG_CONFIG_HOME=' + str(paths['config']))}
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=yes

[Install]
WantedBy=graphical-session.target
""", encoding="utf-8")
    if mode != "none":
        autostart.parent.mkdir(parents=True, exist_ok=True)
        autostart.write_text(f"""[Desktop Entry]
Type=Application
Name=Steam Shaders
Comment=Monitor Steam shader compilation
Exec={desktop_command}
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
""", encoding="utf-8")
    else:
        autostart.unlink(missing_ok=True)
    print(f"Monitor e comando: {lib} / {launcher}")
    print(f"Inicialização: {mode}")
    print(f"Extensão GNOME: {extension}" if with_gnome else
          "Sem extensão GNOME nesta sessão; monitor, notificações e terminal disponíveis.")
    if not root and str(launcher.parent) not in os.environ.get("PATH", "").split(os.pathsep):
        print(f"O comando ainda não está no PATH. Use {launcher} ou entre novamente na sessão.")
    return dict(paths, startup=mode, gnome=with_gnome)


def configure_next_login():
    script = f"""const Gio = imports.gi.Gio;
const settings = new Gio.Settings({{schema_id: 'org.gnome.shell'}});
const enabled = settings.get_strv('enabled-extensions');
if (!enabled.includes({json.dumps(UUID)}))
    settings.set_strv('enabled-extensions', [...enabled, {json.dumps(UUID)}]);
Gio.Settings.sync();
"""
    subprocess.run(["gjs", "-c", script], check=True, timeout=10)


def activate(paths):
    if paths["startup"] == "systemd":
        from .cli import stop_monitor
        for arguments in (["daemon-reload"], ["enable", SERVICE], ["stop", SERVICE]):
            subprocess.run(["systemctl", "--user", *arguments], check=True, timeout=20)
        stop_monitor(paths["data"] / APP_ID)
        subprocess.run(["systemctl", "--user", "start", SERVICE], check=True, timeout=20)
    elif paths["startup"] == "autostart":
        from .cli import stop_monitor
        state = paths["data"] / APP_ID
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        stop_monitor(state)
        with (state / "monitor.log").open("ab") as log:
            subprocess.Popen([sys.executable, str(paths["lib"] / "run.py"), "run"],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             start_new_session=True)
    if paths["gnome"]:
        if shutil.which("gnome-extensions"):
            result = subprocess.run(["gnome-extensions", "enable", UUID], capture_output=True, timeout=10)
        else:
            result = None
        if result is None or result.returncode:
            if shutil.which("gjs"):
                configure_next_login()
            print("A extensão precisa de um novo login; habilite Steam Shaders no aplicativo Extensões.")
        else:
            print("Extensão habilitada. Atualizações do código aparecem após sair e entrar na sessão.")


def uninstall(root=None):
    paths = locations(root)
    unit = paths["config"] / "systemd/user" / SERVICE
    if not root:
        if unit.exists() and systemd_available():
            subprocess.run(["systemctl", "--user", "disable", "--now", SERVICE], check=True, timeout=20)
        if shutil.which("gnome-extensions") and gnome_supported():
            subprocess.run(["gnome-extensions", "disable", UUID], capture_output=True, timeout=10)
        from .cli import stop_monitor
        stop_monitor(paths["data"] / APP_ID)
    extension = paths["data"] / "gnome-shell/extensions" / UUID
    targets = [paths["lib"] / "steam_shaders" / name for name in PROGRAM_FILES]
    targets += [paths["lib"] / name for name in (*LEGACY_FILES, "run.py")]
    targets += [extension / name for name in EXTENSION_FILES]
    targets += [unit, paths["config"] / "autostart/steam-shaders.desktop", paths["bin"]]
    for target in targets:
        target.unlink(missing_ok=True)
    if not root and systemd_available():
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, timeout=10)
    print("Programa e inicialização removidos. Histórico e configuração preservados.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--root", type=Path, help="Prepara instalação isolada, sem alterar a sessão")
    parser.add_argument("--activate", action="store_true", help="Inicia o monitor e habilita a extensão agora")
    parser.add_argument("--startup", choices=["auto", "systemd", "autostart", "none"], default="auto")
    parser.add_argument("--gnome", choices=["auto", "yes", "no"], default="auto")
    parser.add_argument("--uninstall", action="store_true", help="Remove o programa, preservando os dados")
    parser.add_argument("--yes", action="store_true", help="Confirma a desinstalação")
    args = parser.parse_args(argv)
    if sys.platform != "linux":
        parser.error("Este projeto requer Linux.")
    if sys.version_info < (3, 9):
        parser.error("É necessário Python 3.9 ou mais recente.")
    if os.geteuid() == 0 and not args.root:
        parser.error("Execute sem sudo: a instalação pertence ao seu usuário.")
    if args.root and args.activate:
        parser.error("--root e --activate não podem ser usados juntos")
    if args.uninstall and args.activate:
        parser.error("--uninstall e --activate não podem ser usados juntos")
    try:
        if args.uninstall:
            if not args.yes and input("Remover Steam Shaders e preservar seus dados? [s/N] ").lower() != "s":
                print("Desinstalação cancelada.")
                return
            uninstall(args.root)
        else:
            paths = install(args.root, args.startup, args.gnome)
            if args.activate:
                activate(paths)
            else:
                print("Preparado. A inicialização configurada será usada no próximo login.")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Falha na instalação/ativação: {error}\n")


if __name__ == "__main__":
    main()
