#!/usr/bin/env python3
"""Inclui licença e fonte da biblioteca de runtime embarcada no build do Decky."""

import shutil

from bundle_backend import ROOT, STAGING

source = ROOT / "node_modules/@decky/api"
target = STAGING / "vendor/decky-api"
if not (source / "LICENSE").is_file():
    raise SystemExit("Execute pnpm install --frozen-lockfile antes de compilar.")
target.mkdir(parents=True, exist_ok=True)
for name in ("LICENSE", "package.json", "README.md"):
    shutil.copy2(source / name, target / name)
shutil.copytree(source / "src", target / "src", dirs_exist_ok=True)
