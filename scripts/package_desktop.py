#!/usr/bin/env python3
"""Empacota a instalação desktop: só o programa, a extensão GNOME e as licenças."""

from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from steam_shaders.installer import EXTENSION_FILES, PROGRAM_FILES, extension_source  # noqa: E402
from steam_shaders.support import VERSION  # noqa: E402

DOCUMENTS = ("install.py", "README.md", "README.pt-BR.md", "LICENSE", "CHANGELOG.md")


def desktop_files():
    files = [ROOT / name for name in DOCUMENTS]
    files += [ROOT / "steam_shaders" / name for name in PROGRAM_FILES]
    files += [extension_source(name) for name in EXTENSION_FILES]
    return files


def clean(info):
    # Não grava o usuário e as permissões da máquina que gerou o pacote.
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mode = 0o755 if info.isdir() else 0o644
    return info


def main(output=None):
    output = Path(output) if output else ROOT / "dist"
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"steam-shaders-desktop-{VERSION}.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for source in desktop_files():
            archive.add(source, arcname=str(Path("steam-shaders") / source.relative_to(ROOT)), filter=clean)
    print(path)
    return path


if __name__ == "__main__":
    main()
