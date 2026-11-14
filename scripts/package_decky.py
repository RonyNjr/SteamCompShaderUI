#!/usr/bin/env python3
"""Empacota o build local no layout ZIP aceito pelo Decky Loader."""

import json
from pathlib import Path
import zipfile

from bundle_backend import DECKY_MODULES, ROOT, STAGING, bundle

ROOT_FILES = ("plugin.json", "package.json", "main.py", "README.md", "README.pt-BR.md", "LICENSE",
              "THIRD_PARTY_NOTICES.md", "CHANGELOG.md", "rollup.config.js", "tsconfig.json", "pnpm-lock.yaml")
# Fontes para reconstruir a interface com outra versão do @decky/api (LGPL).
# Testes, extensão GNOME, imagens e instalador desktop não servem no Steam Deck.
SOURCE_DIRS = ("integrations/decky", "integrations/shared", "scripts", "docs")
SOURCE_TYPES = {".py", ".js", ".ts", ".tsx", ".json", ".md"}


def source_files():
    files = [ROOT / name for name in ROOT_FILES]
    files += [ROOT / "steam_shaders" / name for name in DECKY_MODULES]
    for directory in SOURCE_DIRS:
        files += sorted(path for path in (ROOT / directory).rglob("*")
                        if path.is_file() and path.suffix in SOURCE_TYPES)
    return files


def main():
    if not (STAGING / "dist/index.js").is_file():
        raise SystemExit("Execute pnpm run build antes de empacotar.")
    bundle()
    version = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    output = ROOT / "dist" / f"steam-shaders-{version}.zip"
    output.parent.mkdir(exist_ok=True)
    vendor = STAGING / "vendor/decky-api"
    if not (vendor / "LICENSE").exists():
        raise SystemExit("Avisos de dependências ausentes. Execute pnpm run build.")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in source_files():
            archive.write(path, str(Path("steam-shaders") / path.relative_to(ROOT)))
        runtime = sorted((STAGING / "dist").glob("index.js*"))
        runtime += sorted((STAGING / "py_modules").rglob("*.py"))
        runtime += sorted(path for path in vendor.rglob("*") if path.is_file())
        for path in runtime:
            archive.write(path, str(Path("steam-shaders") / path.relative_to(STAGING)))
    print(output)


if __name__ == "__main__":
    main()
