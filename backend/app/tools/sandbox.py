"""Run legacy R code in a locked-down Docker sandbox (no network, read-only, CPU/mem/time limits).

If Docker is not available, falls back to *reference outputs* recorded from an earlier
sandbox run with byte-identical inputs (the result says which path was used).
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings


@dataclass
class SandboxResult:
    ok: bool
    mode: str  # docker | reference
    elapsed_s: float
    stdout: str = ""
    stderr: str = ""
    command: list[str] = field(default_factory=list)
    input_hash: str = ""


def _hash_inputs(script: Path, inputs: list[Path]) -> str:
    h = hashlib.sha256(script.read_bytes())
    for p in inputs:
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        r = subprocess.run(["docker", "image", "inspect", settings.sandbox_image],
                           capture_output=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def run_r(script: Path, workdir: Path, args: list[str], inputs: list[Path], outputs: list[str]) -> SandboxResult:
    """Run `Rscript /model/<script> args...` with `workdir` mounted at /work."""
    workdir = workdir.resolve()
    input_hash = _hash_inputs(script, inputs)
    ref_dir = script.parent / "reference" / input_hash[:16]
    mode = settings.sandbox_mode
    use_docker = mode == "docker" or (mode == "auto" and docker_available())

    t0 = time.perf_counter()
    if use_docker:
        cmd = ["docker", "run", "--rm", "--network", "none", "--cpus", "1", "--memory", "1g",
               "--pids-limit", "128", "--read-only", "--tmpfs", "/tmp",
               "--security-opt", "no-new-privileges",
               "-v", f"{script.parent.resolve()}:/model:ro", "-v", f"{workdir}:/work",
               settings.sandbox_image, f"/model/{script.name}", *args]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=settings.sandbox_timeout)
        except subprocess.TimeoutExpired:
            return SandboxResult(False, "docker", time.perf_counter() - t0, "", "timeout", cmd, input_hash)
        ok = r.returncode == 0 and all((workdir / o).exists() for o in outputs)
        if ok:  # record reference outputs for offline replay
            ref_dir.mkdir(parents=True, exist_ok=True)
            for o in outputs:
                shutil.copy(workdir / o, ref_dir / Path(o).name)
            (ref_dir / "stdout.txt").write_text(r.stdout)
        return SandboxResult(ok, "docker", time.perf_counter() - t0, r.stdout, r.stderr[-4000:], cmd, input_hash)

    if ref_dir.exists():
        for o in outputs:
            (workdir / o).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ref_dir / Path(o).name, workdir / o)
        out = (ref_dir / "stdout.txt").read_text() if (ref_dir / "stdout.txt").exists() else ""
        return SandboxResult(True, "reference", time.perf_counter() - t0, out, "", [], input_hash)
    return SandboxResult(False, "unavailable", 0.0, "", "Docker sandbox unavailable and no reference output "
                         "recorded for these inputs. Build it with `make sandbox`.", [], input_hash)


HARNESS = Path(__file__).resolve().parents[1] / "modelkit" / "instrument"


def run_instrumented(model_dir: Path, script_name: str, epilogue: str, workdir: Path, data_room: Path,
                     inputs: list[Path], outputs: list[str]) -> SandboxResult:
    """Run an UNMODIFIED legacy script via the harness: it is sourced as-is, then a factory-written
    epilogue exports the objects needed for parity (scores, coefficients, splits).
    Mounts: /model (ro, the legacy code) · /harness (ro) · /work (rw) · /shared/riskdata (rw, the data room)."""
    workdir, data_room = workdir.resolve(), data_room.resolve()
    (workdir / "out").mkdir(parents=True, exist_ok=True)
    script = model_dir / script_name
    input_hash = _hash_inputs(script, inputs + [HARNESS / epilogue])
    ref_dir = model_dir / "reference" / input_hash[:16]
    use_docker = settings.sandbox_mode == "docker" or (settings.sandbox_mode == "auto" and docker_available())
    t0 = time.perf_counter()
    if use_docker:
        cmd = ["docker", "run", "--rm", "--network", "none", "--cpus", "2", "--memory", "2g", "--pids-limit", "256",
               "--read-only", "--tmpfs", "/tmp", "--security-opt", "no-new-privileges",
               "-v", f"{model_dir.resolve()}:/model:ro", "-v", f"{HARNESS}:/harness:ro",
               "-v", f"{workdir}:/work", "-v", f"{data_room}:/shared/riskdata",
               settings.sandbox_image, "/harness/run_legacy.R", f"/model/{script_name}", f"/harness/{epilogue}"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=max(settings.sandbox_timeout, 300))
        except subprocess.TimeoutExpired:
            return SandboxResult(False, "docker", time.perf_counter() - t0, "", "timeout", cmd, input_hash)
        ok = r.returncode == 0 and all((workdir / o).exists() for o in outputs)
        if ok:
            ref_dir.mkdir(parents=True, exist_ok=True)
            for o in outputs:
                shutil.copy(workdir / o, ref_dir / Path(o).name)
            (ref_dir / "stdout.txt").write_text(r.stdout)
        return SandboxResult(ok, "docker", time.perf_counter() - t0, r.stdout[-6000:], r.stderr[-4000:], cmd, input_hash)
    if ref_dir.exists():
        for o in outputs:
            (workdir / o).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ref_dir / Path(o).name, workdir / o)
        out = (ref_dir / "stdout.txt").read_text() if (ref_dir / "stdout.txt").exists() else ""
        return SandboxResult(True, "reference", time.perf_counter() - t0, out, "", [], input_hash)
    return SandboxResult(False, "unavailable", 0.0, "", "Docker sandbox unavailable and no reference output for these inputs.",
                         [], input_hash)
