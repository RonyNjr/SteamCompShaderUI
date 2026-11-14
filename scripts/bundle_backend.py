#!/usr/bin/env python3
"""Inclui o monitor padrão no pacote Python do Decky, sem cópia manual de código."""

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "build/decky"
# Só o que roda no Steam Deck; terminal e instalador pertencem ao desktop.
DECKY_MODULES = ("__init__.py", "monitor.py", "support.py", "decky.py")


def bundle():
    target = STAGING / "py_modules/steam_shaders"
    shutil.rmtree(target, ignore_errors=True)  # Não carrega módulos de builds anteriores.
    target.mkdir(parents=True)
    (STAGING / "py_modules/__init__.py").unlink(missing_ok=True)
    for name in DECKY_MODULES:
        shutil.copy2(ROOT / "steam_shaders" / name, target / name)


if __name__ == "__main__":
    bundle()
