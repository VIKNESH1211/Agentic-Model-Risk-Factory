"""Content-addressed file store for uploaded scripts and data (var/store/<sha[:2]>/<sha>).

The database keeps names, versions and metadata; bytes live here once, whatever their name.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from app.core.config import settings

STORE = settings.var_dir / "store"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def path_of(sha: str) -> Path:
    return STORE / sha[:2] / sha


def put_bytes(data: bytes) -> str:
    sha = sha256_bytes(data)
    p = path_of(sha)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)
    return sha


def put_file(src: Path) -> str:
    return put_bytes(Path(src).read_bytes())


def read_text(sha: str) -> str:
    return path_of(sha).read_text(errors="replace")


def copy_to(sha: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path_of(sha), dest)
    return dest
