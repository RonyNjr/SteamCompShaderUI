#!/usr/bin/env python3
"""Inclui o monitor padrão no pacote Python do Decky, sem cópia manual de código."""

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "build/decky"


def bundle():
    target = STAGING / "py_modules/steam_shaders"
    target.mkdir(parents=True, exist_ok=True)
    (STAGING / "py_modules/__init__.py").unlink(missing_ok=True)
    for source in (ROOT / "steam_shaders").glob("*.py"):
        shutil.copy2(source, target / source.name)


if __name__ == "__main__":
    bundle()
