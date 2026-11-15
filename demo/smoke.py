"""End-to-end check of the v3 platform through its public API (no internal imports).

  fresh DB → onboard the test estate → every model through the factory (demo delegate approves each gate)
  → certificates, plan-driven validation, traffic-checked reports → live traffic on ≥2 models → drift → alert

Usage: DEMO_API=http://localhost:8100 python demo/smoke.py [--keep]   (--keep: don't re-run on an existing estate)
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

API = os.getenv("DEMO_API", "http://localhost:8100")
FAIL: list[str] = []


def call(method: str, path: str, body=None, timeout=60):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data, method=method, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or "null")


def check(ok: bool, msg: str):
    print(("  ✓ " if ok else "  ✗ ") + msg)
    if not ok:
        FAIL.append(msg)


def wait(pred, timeout: float, every: float = 5, label: str = ""):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(every)
        print(f"    … {label} {int(time.time() - t0)}s", end="\r")
    return None


def main():
    h = call("GET", "/api/health")
    print(f"health: llm {h['llm']['provider']}:{h['llm']['model']} live={h['llm']['live']} · docker={h['sandbox_docker']}")
    if "--keep" not in sys.argv:
        print("reset (all) + onboard test estate")
        r = call("POST", "/api/demo/reset", {"scope": "all", "seed": True}, timeout=180)
        check(len(r["seeded"]["models"]) == 5, f"5 test models onboarded ({r['seeded']['models']})")
    models = [m["id"] for m in call("GET", "/api/models")]
    print(f"factory: {models} (demo delegate approves every gate)")
    call("POST", "/api/runs", {"auto_approve": True})

    def done():
        runs = [r for r in call("GET", "/api/runs") if r["kind"] == "factory"]
        return runs if runs and all(r["status"] in ("completed", "failed", "rejected") for r in runs) else None
    runs = wait(done, 60 * 60, 10, "factory") or []
    print()
    for r in sorted(runs, key=lambda r: r["model_id"]):
        m = call("GET", f"/api/models/{r['model_id']}")
        meta = m["model"]["meta"]
        rep = m["reports"][-1] if m["reports"] else None
        print(f"  {r['model_id']}: run {r['status']:<9} parity={meta.get('parity_verdict')} report={'clean' if rep and rep['checker_ok'] else rep}"
              f" deployed={meta.get('deployed', False)} findings={len(m['findings'])} error={meta.get('lifecycle', {}).get('error', '')[:80]}")
        check(r["status"] == "completed", f"{r['model_id']} completed the factory")
        check(meta.get("parity_verdict") in ("PASS", "REHOSTED"), f"{r['model_id']} certified ({meta.get('parity_verdict')})")
        check(bool(rep and rep["checker_ok"]), f"{r['model_id']} report has no unsourced numbers")
        spec = call("GET", f"/api/models/{r['model_id']}/spec")["current"]
        check(spec and spec["status"] == "approved", f"{r['model_id']} spec approved (v{spec and spec['version']})")
    live = call("GET", "/api/traffic")
    check(len(live) >= 2, f"{len(live)} models serving live traffic")
    if live:
        mid = live[0]["model_id"]
        st = call("GET", f"/api/traffic/{mid}")
        sc = st["plan"]["scenarios"]
        check(bool(st["plan"]["panels"]), f"{mid} dashboard has {len(st['plan']['panels'])} plan-defined panels")
        if sc:
            print(f"drift: ramping '{sc[0]['id']}' on {mid}")
            call("POST", f"/api/traffic/{mid}/scenario", {"scenario": sc[0]["id"], "severity": 1.0, "ramp_s": 10})
            al = wait(lambda: call("GET", f"/api/traffic/{mid}")["alerts"], 240, 10, "alerts")
            print()
            check(bool(al), f"{mid}: drift raised {len(al or [])} alert(s)")
            call("POST", f"/api/traffic/{mid}/scenario", {"scenario": None, "severity": 0, "ramp_s": 10})
    v = call("POST", "/api/ledger/verify")
    check(v["ok"], f"ledger intact ({v['checked']} entries)")
    print("\nRESULT:", "PASS" if not FAIL else f"{len(FAIL)} failure(s): " + "; ".join(FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
