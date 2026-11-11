"""Red-team agent: adversarial slice search and stress tests on the validated model."""
from __future__ import annotations

import re

import pandas as pd

from app.agents.common import StageCtx
from app.core.config import settings
from app.evidence import metric_store

SLICE_COLS = ["purpose", "status.of.existing.checking.account", "credit.history", "savings.account.and.bonds",
              "present.employment.since", "sex", "age_band"]
MIN_SLICE = 60


def run(ctx: StageCtx, *, model, data: pd.DataFrame, vctx: dict) -> dict:
    rec = ctx.recorder()
    S = vctx["scored"]
    overall = metric_store.value(ctx.run_id, "gini.oot")
    scored = pd.read_csv(settings.var_dir / S)

    def slice_search():
        res = []
        for c in SLICE_COLS:
            for v, n in scored[c].astype(str).value_counts().items():
                if n < MIN_SLICE:
                    continue
                sub = scored[scored[c].astype(str) == v]
                if sub["y"].nunique() < 2:
                    continue
                name = re.sub(r"[^A-Za-z0-9_.=-]+", "_", f"gini.slice.{c.split('.')[0][:12]}={v[:24]}")
                g = rec.measure(name, {"fn": "gini", "artifact": S, "split": "all", "slice": f"{c}={v}"}, emit=False)
                res.append((g, name, c, v, n))
        return sorted(res)
    sl = ctx.tool("slice_search", f"Gini on every segment with ≥{MIN_SLICE} applicants", slice_search,
                  result_summary=lambda r: f"{len(r)} slices, worst {r[0][0]:.3f}" if r else "none")
    overall_all = rec.measure("gini.all", {"fn": "gini", "artifact": S, "split": "all"})

    def stress():
        st = data.copy().astype({"credit.amount": float})
        st["credit.amount"] = st["credit.amount"] * 1.2
        out = pd.DataFrame({"id": data["id"], "split": data["split"], "pd": model.predict_pd(data),
                            "pd_stress": model.predict_pd(st)})
        f = ctx.dir / "stress_amount_120.csv"
        out.to_csv(f, index=False)
        return rec.measure("decision_flips.stress_amount_120",
                           {"fn": "decision_flips", "artifact": f"{ctx.rel}/stress_amount_120.csv", "split": "all",
                            "a": "pd", "b": "pd_stress", "cutoff": model.cutoff},
                           definition="Applicants whose decision flips when every loan amount is raised 20%")
    flips = ctx.tool("stress_test", "loan amount +20% for every applicant", stress,
                     result_summary=lambda r: f"{int(r)} decision flips")
    rec.commit("red-team")

    if sl and sl[0][0] < overall_all - 0.2:
        g, name, c, v, n = sl[0]
        ctx.finding("medium", "segment_weakness", f"Weak discrimination in segment {c.split('.')[0]} = `{v}`",
                    "Model ranks risk much worse in this segment than overall; consider segment-specific review.",
                    detector="slice_search", evidence={"tokens": [ctx.tok(name), ctx.tok("gini.all")]})
    if flips > 0:
        ctx.finding("low", "sensitivity", "Decisions sensitive to modest loan-amount inflation",
                    "A uniform 20% increase in requested amount flips approve/decline decisions; amount bins create cliffs.",
                    detector="stress_test", evidence={"tokens": [ctx.tok("decision_flips.stress_amount_120")]})
    return {"worst_slice": sl[0][1] if sl else None, "overall": overall}
