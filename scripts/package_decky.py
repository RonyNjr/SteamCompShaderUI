#!/usr/bin/env python3
"""Empacota o build local no layout ZIP aceito pelo Decky Loader."""

import json
from pathlib import Path
import zipfile

from bundle_backend import ROOT, STAGING, bundle


def main():
    if not (STAGING / "dist/index.js").is_file():
        raise SystemExit("Execute pnpm run build antes de empacotar.")
    bundle()
    version = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    output = ROOT / "dist" / f"steam-shaders-{version}.zip"
    output.parent.mkdir(exist_ok=True)
    files = [ROOT / name for name in ("plugin.json", "package.json", "main.py", "README.md",
                                     "README.pt-BR.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "install.py",
                                     "rollup.config.js", "tsconfig.json", "pnpm-lock.yaml", "CHANGELOG.md")]
    allowed = {".py", ".js", ".mjs", ".ts", ".tsx", ".json", ".css", ".svg", ".md", ".png"}
    for directory in ("steam_shaders", "integrations", "scripts", "tests", "docs"):
        files += sorted(path for path in (ROOT / directory).rglob("*")
                        if path.is_file() and path.suffix in allowed)
    vendor = STAGING / "vendor/decky-api"
    if not (vendor / "LICENSE").exists():
        raise SystemExit("Avisos de dependências ausentes. Execute pnpm run build.")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, str(Path("steam-shaders") / path.relative_to(ROOT)))
        runtime = sorted((STAGING / "dist").glob("index.js*"))
        runtime += sorted((STAGING / "py_modules").rglob("*.py"))
        runtime += sorted(path for path in vendor.rglob("*") if path.is_file())
        for path in runtime:
            archive.write(path, str(Path("steam-shaders") / path.relative_to(STAGING)))
    print(output)


if __name__ == "__main__":
    main()
