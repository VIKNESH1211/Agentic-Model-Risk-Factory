"""Run any onboarded legacy R model, unmodified, in the locked-down Docker sandbox.

Layout of one sandbox run (base = <run dir>/sandbox):
  base/model     ro  /model              the uploaded scripts
  base/harness   ro  /harness            run_legacy.R + the epilogue (probe or agent-written export)
  base/work      rw  /work               cwd; inputs referenced by relative path are copied here; out/ = exports
  base/riskdata  rw  /shared/riskdata    private copy of the data room (legacy code may write to it)

No network, read-only root, CPU/memory/pid limits. Without Docker, a run replays outputs recorded from an
earlier sandbox run with byte-identical inputs (var/sandbox_cache), and says so.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from app import repositories as repo
from app.core import storage
from app.core.config import settings
from app.domain.schemas import ModelSpec
from app.services import onboarding

R_DIR = Path(__file__).parent / "r"
CACHE = settings.var_dir / "sandbox_cache"


@dataclass
class LegacyRun:
    ok: bool
    mode: str  # docker | replay | unavailable
    elapsed_s: float
    stdout: str = ""
    stderr: str = ""
    out_dir: Path = Path()
    input_hash: str = ""
    command: list[str] = field(default_factory=list)

    @property
    def error(self) -> str:
        lines = [l.strip() for l in (self.stderr or "").splitlines() if l.strip()]
        return "\n".join(lines[-10:])[:1500]  # R puts the useful cause (e.g. which file) in the warnings before the error


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "image", "inspect", settings.sandbox_image], capture_output=True, timeout=10).returncode == 0
    except Exception:
        return False


def _is_relative(ref: str) -> bool:
    return not (ref.startswith("/") or ref.startswith("\\") or (len(ref) > 1 and ref[1] == ":"))


def prepare(model_id: str, spec: ModelSpec, base: Path, epilogue: str | None) -> str:
    """Lay out the sandbox directories. Returns the input hash (scripts + data + epilogue + args)."""
    shutil.rmtree(base, ignore_errors=True)
    for d in ("model", "harness", "work/out", "riskdata"):
        (base / d).mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    for f in sorted(onboarding.files_of(model_id, "script"), key=lambda f: f.name):
        storage.copy_to(f.sha256, base / "model" / f.name)
        h.update(f"{f.name}:{f.sha256}".encode())
    for a in sorted(repo.assets.list(is_current=True), key=lambda a: a.name):
        storage.copy_to(a.sha256, base / "riskdata" / a.name)
        h.update(f"{a.name}:{a.sha256}".encode())
    for m in spec.inputs:
        a = repo.current_asset(m.asset)
        if a and _is_relative(m.ref):
            storage.copy_to(a.sha256, base / "work" / m.ref)
            h.update(f"{m.ref}->{a.sha256}".encode())
    shutil.copy(R_DIR / "run_legacy.R", base / "harness" / "run_legacy.R")
    shutil.copy(R_DIR / "mrf_export.R", base / "harness" / "mrf_export.R")
    h.update((R_DIR / "mrf_export.R").read_bytes())
    epi = (R_DIR / "probe.R").read_text() if epilogue is None else epilogue
    (base / "harness" / "epilogue.R").write_text(epi)
    h.update(epi.encode())
    h.update("\0".join([spec.entry_script, *spec.harness.args]).encode())
    return h.hexdigest()


def run(model_id: str, spec: ModelSpec, base: Path, epilogue: str | None = None) -> LegacyRun:
    """epilogue=None runs the generic probe; otherwise the given R code runs after the legacy script."""
    if not spec.entry_script or not (onboarding.files_of(model_id, "script")):
        return LegacyRun(False, "unavailable", 0.0, stderr="no entry script in the spec")
    ih = prepare(model_id, spec, base, epilogue)
    out = base / "work" / "out"
    cache = CACHE / ih[:20]
    t0 = time.perf_counter()
    if settings.sandbox_mode != "reference" and docker_available():
        cmd = ["docker", "run", "--rm", "--network", "none", "--cpus", "2", "--memory", "2g", "--pids-limit", "256",
               "--read-only", "--tmpfs", "/tmp", "--security-opt", "no-new-privileges",
               "-v", f"{(base / 'model').resolve()}:/model:ro", "-v", f"{(base / 'harness').resolve()}:/harness:ro",
               "-v", f"{(base / 'work').resolve()}:/work", "-v", f"{(base / 'riskdata').resolve()}:/shared/riskdata",
               settings.sandbox_image, "/harness/run_legacy.R", f"/model/{spec.entry_script}", "/harness/epilogue.R",
               *spec.harness.args]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=max(settings.sandbox_timeout, 300))
        except subprocess.TimeoutExpired:
            return LegacyRun(False, "docker", time.perf_counter() - t0, stderr="timeout", out_dir=out, input_hash=ih, command=cmd)
        ok = r.returncode == 0
        if ok:  # record outputs so the same inputs replay without Docker
            shutil.rmtree(cache, ignore_errors=True)
            shutil.copytree(out, cache / "out")
            (cache / "stdout.txt").write_text(r.stdout)
        return LegacyRun(ok, "docker", time.perf_counter() - t0, r.stdout[-6000:], r.stderr[-4000:], out, ih, cmd)
    if (cache / "out").exists():
        shutil.rmtree(out, ignore_errors=True)
        shutil.copytree(cache / "out", out)
        return LegacyRun(True, "replay", time.perf_counter() - t0, (cache / "stdout.txt").read_text(), "", out, ih)
    return LegacyRun(False, "unavailable", 0.0, stderr="Docker sandbox unavailable and no recorded run for these exact inputs "
                     "(build it with `make sandbox`).", out_dir=out, input_hash=ih)
