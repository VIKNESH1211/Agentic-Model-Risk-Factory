"""Onboarding: models and data-room assets enter the platform here (UI upload, API, or `make seed`)."""
from __future__ import annotations

import io
import re
from pathlib import PurePath

import pandas as pd

from app import repositories as repo
from app.core import storage
from app.core.events import bus
from app.domain.tables import DataAsset, Model, ModelFile
from app.evidence import ledger

ID_RE = re.compile(r"\b([A-Z]{2,4}-\d{2,4})\b")
SCRIPT_EXT = {".r"}
REFERENCE_EXT = {".py"}


# ------------------------------------------------------------------ data room
def profile_csv(data: bytes, max_rows: int = 200_000) -> tuple[int, dict]:
    """Rows + per-column profile (dtype, missing, distinct, examples). Non-CSV files get an empty profile."""
    try:
        df = pd.read_csv(io.BytesIO(data), nrows=max_rows, low_memory=False)
    except Exception:
        return 0, {"columns": [], "note": "not a readable CSV"}
    cols = []
    for c in df.columns:
        s = df[c]
        ex = [str(v)[:40] for v in s.dropna().unique()[:3]]
        cols.append({"name": str(c), "dtype": str(s.dtype), "missing": int(s.isna().sum()),
                     "unique": int(s.nunique(dropna=True)), "example": ex})
    return int(len(df)), {"columns": cols}


def upload_asset(name: str, data: bytes, *, description: str = "", provenance: str = "") -> DataAsset:
    """Add a file to the data room. Same name + new bytes = new version (the old one stays for lineage)."""
    name = PurePath(name).name
    sha = storage.put_bytes(data)
    cur = repo.current_asset(name)
    if cur and cur.sha256 == sha:
        return cur
    rows, prof = profile_csv(data)
    if cur:
        repo.assets.update(cur.id, is_current=False)
    a = repo.assets.create(DataAsset(name=name, version=(cur.version + 1) if cur else 1, sha256=sha, size=len(data),
                                     rows=rows, profile=prof, description=description or (cur.description if cur else ""),
                                     provenance=provenance or (cur.provenance if cur else "")))
    ledger.append("human", "data_asset_uploaded", {"name": name, "version": a.version, "sha256": sha, "rows": rows})
    bus.publish("info", f"Data room: {name} v{a.version} ({rows:,} rows)", agent="system")
    return a


def asset_versions(name: str) -> list[DataAsset]:
    return sorted(repo.assets.list(name=name), key=lambda a: a.version, reverse=True)


# ------------------------------------------------------------------ models
def _role(filename: str) -> str:
    ext = PurePath(filename).suffix.lower()
    return "script" if ext in SCRIPT_EXT else "reference" if ext in REFERENCE_EXT else "doc"


def _derive_id(files: list[tuple[str, bytes]]) -> str:
    for name, data in files:
        if _role(name) == "script":
            m = ID_RE.search(data[:2000].decode(errors="ignore"))
            if m:
                return m.group(1)
    stem = PurePath(next((n for n, _ in files if _role(n) == "script"), files[0][0])).stem
    return re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-").upper()[:24] or "MODEL"


def create_model(files: list[tuple[str, bytes]], *, model_id: str | None = None, name: str = "", owner: str = "",
                 description: str = "") -> Model:
    """Register a model from its uploaded files. Nothing about it is known yet: the intake agent works it out."""
    if not any(_role(n) == "script" for n, _ in files):
        raise ValueError("upload at least one R script (.R)")
    mid = (model_id or _derive_id(files)).strip().upper()
    if repo.models.get(mid):
        raise ValueError(f"model {mid} already exists")
    m = repo.models.create(Model(id=mid, name=name or mid, owner=owner, description=description, language="R",
                                 status="onboarded", meta={"lifecycle": {"stage": "onboarded", "status": "idle"}}))
    for fname, data in files:
        add_file(mid, fname, data)
    ledger.append("human", "model_onboarded", {"model_id": mid, "files": [n for n, _ in files]})
    bus.publish("info", f"Model {mid} onboarded ({len(files)} file(s))", model_id=mid, agent="system")
    return m


def add_file(model_id: str, filename: str, data: bytes, role: str | None = None) -> ModelFile:
    fname = PurePath(filename).name
    old = repo.model_files.first(model_id=model_id, name=fname)
    if old:
        repo.model_files.delete(old.id)
    return repo.model_files.create(ModelFile(model_id=model_id, name=fname, role=role or _role(fname),
                                             sha256=storage.put_bytes(data), size=len(data)))


def files_of(model_id: str, role: str | None = None) -> list[ModelFile]:
    return [f for f in repo.model_files.list(model_id=model_id) if role is None or f.role == role]


def script_text(model_id: str, name: str | None = None) -> tuple[str, str]:
    """(file name, text) of the entry script (or a named file)."""
    fs = files_of(model_id)
    f = next((f for f in fs if f.name == name), None) if name else None
    f = f or next((f for f in fs if f.role == "script"), None)
    if f is None:
        raise ValueError(f"{model_id} has no script")
    return f.name, storage.read_text(f.sha256)


def delete_model(model_id: str) -> None:
    for f in files_of(model_id):
        repo.model_files.delete(f.id)
    for r in repo.specs.versions(model_id):
        repo.specs.delete(r.id)
    for k in ("validation", "monitoring"):
        for r in repo.plans.versions(model_id, k):
            repo.plans.delete(r.id)
    repo.models.delete(model_id)
    ledger.append("human", "model_deleted", {"model_id": model_id})
