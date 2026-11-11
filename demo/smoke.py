"""End-to-end smoke test of the exact demo path, through the public API.
Usage: DEMO_API=http://localhost:8100 python demo/smoke.py   (soak: add --times 10)"""
import json
import os
import sys
import time
import urllib.request

API = os.getenv("DEMO_API", "http://localhost:8100")


def call(method, path, body=None):
    req = urllib.request.Request(API + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def wait(pred, timeout=600, every=2):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(every)
    raise TimeoutError


def check(name, cond):
    print(("  ✓ " if cond else "  ✗ ") + name)
    if not cond:
        sys.exit(1)


def once():
    call("POST", "/api/demo/reset")
    call("POST", "/api/runs", {"auto_approve": True})
    runs = wait(lambda: (lambda rs: rs if rs and all(r["status"] in ("completed", "failed") for r in rs) else None)(call("GET", "/api/runs")))
    check("all factory runs completed", all(r["status"] == "completed" for r in runs))
    p = call("GET", "/api/models/CR-001/parity")
    check(f"parity certificate PASS (score Δ {p['certificate']['results']['score_max_abs_diff']:.1e})", p["certificate"]["verdict"] == "PASS")
    rep = call("GET", "/api/reports/CR-001")
    check(f"report has 0 unsourced numbers ({rep['report']['checker']['token_count']} tokens)", rep["report"]["checker"]["ok"])
    tok = next(iter(rep["tokens"]))
    check(f"reproduce {tok}", call("POST", f"/api/evidence/{tok}/reproduce").get("match") in (True, None))
    call("POST", "/api/benchmarks/run")
    b = wait(lambda: (lambda d: d if d.get("complete") else None)(call("GET", "/api/benchmarks/latest")))
    check(f"benchmark {b['summary']['caught']}/{b['summary']['planted']} caught, {b['summary']['false_alarms']} false alarms",
          b["summary"]["caught"] >= 8 and b["summary"]["false_alarms"] == 0)
    for m in ("PR-001", "FR-001", "CR-003"):
        check(f"{m} parity certificate PASS", call("GET", f"/api/models/{m}/parity")["certificate"]["verdict"] == "PASS")
    check("CR-002 rehosted", call("GET", "/api/models/CR-002/parity")["certificate"]["verdict"] == "REHOSTED")
    check("4 models serving live traffic", len(call("GET", "/api/traffic")) == 4)
    call("POST", "/api/traffic/CR-001/scenario", {"scenario": "mixed", "severity": 0.9, "ramp_s": 15})
    rv = wait(lambda: (call("GET", "/api/traffic/CR-001")["revalidations"] or [None])[0], timeout=300, every=5)
    check(f"drift alert → automatic re-validation {rv['id']}", True)
    rv = wait(lambda: next((r for r in call("GET", "/api/traffic/CR-001")["revalidations"] if r["status"] in ("waiting_gate", "completed")), None), timeout=300)
    check("re-validation report diff available", len(call("GET", f"/api/reports/rep_{rv['id']}/diff")["rows"]) > 0)
    check("prompt injection flagged and ignored", call("POST", "/api/security/injection-test")["passed"])
    check("ledger verifies", call("POST", "/api/ledger/verify")["ok"])
    call("POST", "/api/ledger/_tamper")
    check("tamper detected", not call("POST", "/api/ledger/verify")["ok"])
    call("POST", "/api/demo/reset")


if __name__ == "__main__":
    n = int(sys.argv[sys.argv.index("--times") + 1]) if "--times" in sys.argv else 1
    for i in range(n):
        print(f"demo path run {i + 1}/{n}")
        once()
    print("OK")
