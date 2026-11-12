"""Caminhos e configuração compartilhados, sem dependências externas."""

import json
import os
from pathlib import Path

APP_ID = "steamcompshaderui"
VERSION = "0.2.0"
GNOME_VERSIONS = ("51",)


def xdg_home(variable, fallback):
    # A especificação XDG manda ignorar valores vazios e caminhos relativos.
    value = os.environ.get(variable, "")
    return Path(value) if value and Path(value).is_absolute() else Path.home() / fallback


def data_dir():
    return xdg_home("XDG_DATA_HOME", ".local/share") / APP_ID


def config_path():
    return xdg_home("XDG_CONFIG_HOME", ".config") / APP_ID / "config.json"


def load_config():
    path = config_path()
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise ValueError(f"Não foi possível ler {path}: {error}") from error
    if not isinstance(config, dict):
        raise ValueError(f"{path}: a configuração deve ser um objeto JSON.")
    steam = config.get("steam_dir")
    if steam is not None and (not isinstance(steam, str) or not Path(steam).expanduser().is_absolute()):
        raise ValueError(f"{path}: steam_dir deve ser um caminho absoluto.")
    if "notifications" in config and not isinstance(config["notifications"], bool):
        raise ValueError(f"{path}: notifications deve ser true ou false.")
    return config


def steam_candidates():
    home = Path.home()
    candidates = [
        xdg_home("XDG_DATA_HOME", ".local/share") / "Steam",
        home / ".local/share/Steam",
        home / ".steam/steam",
        home / ".steam/root",
        home / ".steam/debian-installation",
        home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
        home / "snap/steam/common/.local/share/Steam",
    ]
    # ~/.steam/steam costuma ser um link para ~/.local/share/Steam.
    return list(dict.fromkeys(path.resolve() for path in candidates))


def discover_steam():
    found = [path for path in steam_candidates()
             if (path / "steamapps").is_dir() or (path / "logs").is_dir()]

    def log_time(path):
        try:
            return (path / "logs/shader_log.txt").stat().st_mtime
        except OSError:
            return 0

    # Se houver duas instalações, acompanha a que escreveu no log mais recentemente.
    return sorted(found, key=log_time, reverse=True)
