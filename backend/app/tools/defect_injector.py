"""Seeded-defect benchmark: plant known defects, run the validator detectors, score detection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from app.agents.translations.cr001_model import CR001Scorecard, _cut, make_bins
from app.tools.datasets import prepared


class LeakyScorecard(CR001Scorecard):
    vars = CR001Scorecard.vars + ["leak"]

    def make_bins(self, d):
        b = make_bins(d)
        b["leak"] = d["leak_feature"].astype(str)
        return b


class AgeProxyScorecard(CR001Scorecard):
    vars = CR001Scorecard.vars + ["tenure"]

    def make_bins(self, d):
        b = make_bins(d)
        b["tenure"] = _cut(d["years_at_address_proxy"], [-np.inf, 23, 27, 32, 40, np.inf], ["a", "b", "c", "d", "e"])
        return b


class FineBinScorecard(CR001Scorecard):
    def make_bins(self, d):
        b = make_bins(d)
        b["duration"] = _cut(d["duration.in.month"], [-np.inf, 5, 6, 12, 13, 24, 25, 36, 37, np.inf],
                             ["lt5", "5", "6-12", "12", "13-24", "24", "25-36", "36", "37+"])
        return b


@dataclass
class Variant:
    defect_type: str
    title: str
    expected_category: str  # validation_core.Detection.category that should fire
    build: Callable[[pd.DataFrame, int], tuple]  # (data, seed) -> (model, data)
    subtle: bool = False


def _fit(cls, d):
    return cls().fit(d[d["split"] == "train"])


def clean(d, seed):
    return _fit(CR001Scorecard, d), d


def target_leakage(d, seed):
    rng = np.random.default_rng(seed)
    d = d.copy()
    y = (d["creditability"] == "bad").astype(int)
    noisy = np.where(rng.random(len(d)) < 0.1, 1 - y, y)  # label + 10% noise
    d["leak_feature"] = np.where(noisy == 1, "flag_Y", "flag_N")
    return _fit(LeakyScorecard, d), d


def sign_flip(d, seed):
    m = _fit(CR001Scorecard, d)
    m.params["woe_checking"] *= -1.0
    return m, d


def age_proxy(d, seed):
    rng = np.random.default_rng(seed)
    d = d.copy()
    d["years_at_address_proxy"] = d["age.in.years"] + rng.normal(0, 1.5, len(d))
    return _fit(AgeProxyScorecard, d), d


def covariate_drift(d, seed, dur=12.0, amt=1.8):
    m = _fit(CR001Scorecard, d)
    d = d.astype({"duration.in.month": float, "credit.amount": float})
    o = d["split"] == "oot"
    d.loc[o, "duration.in.month"] = d.loc[o, "duration.in.month"] + dur
    d.loc[o, "credit.amount"] = d.loc[o, "credit.amount"] * amt
    return m, d


def subtle_drift(d, seed):
    return covariate_drift(d, seed, dur=2.0, amt=1.0)


def unstable_binning(d, seed):
    return _fit(FineBinScorecard, d), d


def calibration_shift(d, seed, shift=0.6):
    m = _fit(CR001Scorecard, d)
    m.params["const"] += shift
    return m, d


def subtle_calibration(d, seed):
    return calibration_shift(d, seed, shift=0.15)


def train_test_overlap(d, seed):
    d = d.copy()
    tr = d[d["split"] == "train"].sample(frac=0.3, random_state=seed)
    hold_idx = d[d["split"] == "test"].sample(n=min(len(tr), (d["split"] == "test").sum()), random_state=seed).index
    repl = tr.iloc[: len(hold_idx)].copy()
    repl.index = hold_idx
    repl["split"] = "test"
    repl["id"] = d.loc[hold_idx, "id"].values
    d.loc[hold_idx] = repl
    return _fit(CR001Scorecard, d), d


def missing_spike(d, seed):
    rng = np.random.default_rng(seed)
    m = _fit(CR001Scorecard, d)
    d = d.astype({"credit.amount": float})
    h = d["split"].isin(["test", "oot"]) & (rng.random(len(d)) < 0.2)
    d.loc[h, "credit.amount"] = np.nan
    return m, d


VARIANTS: list[Variant] = [
    Variant("clean", "Clean control A", "", clean),
    Variant("target_leakage", "Target leakage (feature = label + noise)", "leakage", target_leakage),
    Variant("sign_flip", "Coefficient sign flip (checking account)", "sign_flip", sign_flip),
    Variant("age_proxy", "Hidden age proxy feature", "age_proxy", age_proxy),
    Variant("covariate_drift", "Silent covariate drift (duration, amount)", "covariate_drift", covariate_drift),
    Variant("unstable_binning", "Arbitrary narrow bins (duration)", "unstable_binning", unstable_binning),
    Variant("calibration_shift", "Calibration shift (intercept +0.6)", "calibration_shift", calibration_shift),
    Variant("train_test_overlap", "Training rows leaked into test sample", "train_test_overlap", train_test_overlap),
    Variant("missing_spike", "Missing-value spike (credit amount)", "missing_spike", missing_spike),
    Variant("subtle_calibration", "Subtle calibration shift (intercept +0.15)", "calibration_shift", subtle_calibration, True),
    Variant("subtle_drift", "Subtle drift (duration +2 months)", "covariate_drift", subtle_drift, True),
    Variant("clean_b", "Clean control B (different split)", "", clean),
]


def data_for(variant: Variant) -> pd.DataFrame:
    d = prepared()
    if variant.defect_type == "clean_b":  # re-split with another seed: tests false alarms on a fresh sample
        rng = np.random.default_rng(11)
        u = rng.random(len(d))
        d = d.copy()
        d["split"] = np.where(u < 0.6, "train", np.where(u < 0.8, "test", "oot"))
    return d
