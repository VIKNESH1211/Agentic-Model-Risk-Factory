"""Business impact of findings, with explicit labelled assumptions returned alongside every number."""
from __future__ import annotations

ASSUMPTIONS = {
    "annual_applications": {"value": 50_000, "unit": "applications / year", "source": "assumed (illustrative)"},
    "avg_ead_gbp": {"value": 5_000, "unit": "GBP", "source": "assumed (illustrative)"},
    "lgd": {"value": 0.45, "unit": "fraction", "source": "assumed (Basel F-IRB senior unsecured)"},
}


def a(name: str) -> float:
    return float(ASSUMPTIONS[name]["value"])


def el_gap_recipe(artifact: str, split: str) -> dict:
    return {"fn": "el_gap", "artifact": artifact, "split": split, "lgd": a("lgd"), "ead": a("avg_ead_gbp"),
            "volume": a("annual_applications"), "assumptions": ["lgd", "avg_ead_gbp", "annual_applications"]}


def affected_recipe(artifact: str, split: str, col: str) -> dict:
    return {"fn": "scaled_rate", "artifact": artifact, "split": split, "col": col,
            "volume": a("annual_applications"), "assumptions": ["annual_applications"]}


# ---------------------------------------------------------------- ROI
ROI_DEFAULTS = {
    "models_per_year": {"value": 40, "source": "assumed"},
    "manual_weeks_per_validation": {"value": 10, "source": "assumed (industry survey range 6-16)"},
    "validator_cost_per_week_gbp": {"value": 3_000, "source": "assumed (loaded FTE cost)"},
    "human_review_hours_per_model": {"value": 16, "source": "assumed (gates + report review)"},
    "hours_per_week": {"value": 37.5, "source": "assumed"},
}


def roi(inputs: dict, measured: dict) -> dict:
    v = {k: float(inputs.get(k, d["value"])) for k, d in ROI_DEFAULTS.items()}
    manual_hours = v["manual_weeks_per_validation"] * v["hours_per_week"]
    factory_hours = measured["factory_runtime_s"] / 3600 + v["human_review_hours_per_model"]
    manual_cost = v["manual_weeks_per_validation"] * v["validator_cost_per_week_gbp"]
    factory_cost = (v["human_review_hours_per_model"] / v["hours_per_week"]) * v["validator_cost_per_week_gbp"] \
        + measured["llm_cost_usd"] * 0.8 + measured.get("compute_cost_gbp", 0.05)
    n = v["models_per_year"]
    return {
        "inputs": {k: {"value": v[k], "source": "user" if k in inputs else ROI_DEFAULTS[k]["source"]} for k in v},
        "measured": {k: {"value": val, "source": "measured"} for k, val in measured.items()},
        "per_model": {"manual_hours": manual_hours, "factory_hours": round(factory_hours, 2),
                      "manual_cost_gbp": manual_cost, "factory_cost_gbp": round(factory_cost, 2)},
        "annual": {"hours_saved": round((manual_hours - factory_hours) * n),
                   "cost_saved_gbp": round((manual_cost - factory_cost) * n),
                   "fte_released": round((manual_hours - factory_hours) * n / (v["hours_per_week"] * 46), 1)},
        "compression_x": round(manual_hours * 3600 / max(measured["factory_runtime_s"], 1)),
        "compression_note": "machine time only; illustrative - human review time is counted separately",
    }
