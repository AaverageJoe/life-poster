"""Pack the whole project into a single self-contained deploy.sh.

Paste deploy.sh into the Raspberry Pi Connect shell and run it. It unpacks the
project to ~/life-poster and runs install.sh.
"""
from __future__ import annotations

import base64
import io
import os
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "deploy.sh")

INCLUDE = [
    "app.py", "serve.py", "config.py", "render.py", "display.py", "worker.py",
    "requirements.txt", "install.sh", "lifeposter.service.tmpl", "README.md",
]
INCLUDE_DIRS = ["templates", "static"]


def _add(tar: tarfile.TarFile, path: str, arc: str):
    with open(path, "rb") as fh:
        data = fh.read()
    info = tarfile.TarInfo(arc)
    info.size = len(data)
    info.mode = 0o755 if arc.endswith(".sh") else 0o644
    tar.addfile(info, io.BytesIO(data))


def build() -> str:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in INCLUDE:
            p = os.path.join(HERE, name)
            if os.path.exists(p):
                _add(tar, p, name)
        for d in INCLUDE_DIRS:
            root = os.path.join(HERE, d)
            for base, _, files in os.walk(root):
                for f in files:
                    if f.endswith((".pyc",)):
                        continue
                    full = os.path.join(base, f)
                    arc = os.path.relpath(full, HERE).replace(os.sep, "/")
                    _add(tar, full, arc)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    wrapped = "\n".join(b64[i:i + 100] for i in range(0, len(b64), 100))

    script = f"""#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Life Poster - one-shot deploy for Raspberry Pi OS 32-bit on a Pi Zero W
# with a Pimoroni Inky Impression 7.3" (Spectra 6).
#
# Paste this whole file into your Raspberry Pi Connect shell and press Enter.
# It unpacks the project to ~/life-poster and runs the installer.
# ---------------------------------------------------------------------------
set -euo pipefail
DEST="${{1:-$HOME/life-poster}}"
echo "==> Unpacking Life Poster into $DEST"
mkdir -p "$DEST"
base64 -d <<'LIFEPOSTER_B64' | tar -xzf - -C "$DEST"
{wrapped}
LIFEPOSTER_B64
echo "==> Unpacked. Starting installer…"
cd "$DEST"
bash install.sh
"""
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(script)
    return OUT


if __name__ == "__main__":
    path = build()
    size = os.path.getsize(path)
    print(f"wrote {path}  ({size} bytes)")
