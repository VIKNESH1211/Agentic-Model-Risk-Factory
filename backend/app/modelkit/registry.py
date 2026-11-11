"""One adapter per legacy model: how to run it, translate it, validate it and serve it.

strategy:
  scorecard  CR-001 — the original specialised path (WoE scorecard, fuzzing, WoE-specific detectors)
  translate  R -> Python with exact parity (PR-001, CR-003, FR-001)
  rehost     run the legacy code as-is and validate its outputs (CR-002: tree models cannot be ported exactly)
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from app.core.config import settings
from app.modelkit import data as D
from app.tools.datasets import RAW_FEATURES, prepared

T = Path(__file__).parent / "translations"


@dataclass
class Spec:
    task: str                     # binary | frequency | rules
    target: str | None            # outcome column in the scored frame
    decision_kind: str            # approve | alert | limit | price
    cutoff: float | None = None   # decline/alert above this score
    groups: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)  # raw inputs for CSI
    exposure: str | None = None
    trained_on_all: bool = False  # legacy fits on 100% of rows (no hold-out)


@dataclass
class Adapter:
    id: str
    folder: str
    script: str
    strategy: str
    spec: Spec
    epilogue: str = ""
    reference: Path | None = None
    class_name: str = ""
    deployable: bool = True
    outputs: list[str] = field(default_factory=list)
    extra_work_files: list[str] = field(default_factory=list)
    contract: str = ""
    code_findings: list[tuple] = field(default_factory=list)  # (severity, category, title, detail, regex)
    scenarios: dict[str, str] = field(default_factory=dict)

    @property
    def dir(self) -> Path:
        return settings.legacy_dir / self.folder

    # -- data -------------------------------------------------------------------------------------
    def frame(self) -> pd.DataFrame:
        return FRAMES[self.id]()

    # -- legacy outputs → (id, score[, decision]) ----------------------------------------------------
    def legacy_scores(self, work: Path, room: Path) -> pd.DataFrame:
        return LEGACY_READERS[self.id](work, room)

    def legacy_coef(self, work: Path) -> pd.Series | None:
        f = work / "out" / "coef.csv"
        return pd.read_csv(f).set_index("term")["estimate"] if f.exists() else None

    # -- python side --------------------------------------------------------------------------------
    def python_fit_score(self, mod, work: Path, room: Path):
        return PY_RUNNERS[self.id](mod, work, room)

    # -- serving / monitoring -------------------------------------------------------------------------
    def traffic_pool(self) -> pd.DataFrame:
        return POOLS[self.id]()

    def drift(self, rows: pd.DataFrame, scenario: str, sev: float, rng: np.random.Generator) -> pd.DataFrame:
        return DRIFTS[self.id](rows.copy(), scenario, float(np.clip(sev, 0, 1)), rng)


# ===================================================================== frames (analysis datasets)
def _credit_frame() -> pd.DataFrame:
    d = prepared().copy()
    d["y"] = (d["creditability"] == "bad").astype(int)
    return d


def _pr_frame() -> pd.DataFrame:
    c = D.datacar()
    c = c[c["exposure"] > 0].reset_index(drop=True)
    c.insert(0, "id", [f"PR{i:05d}" for i in range(1, len(c) + 1)])
    c["split"] = D._split(len(c), 7)  # simulated: the data has no policy dates
    c["agecat"] = c["agecat"].astype(str)
    c["veh_age"] = c["veh_age"].astype(str)
    return c


def _fr_frame(train_rows: np.ndarray | None = None) -> pd.DataFrame:
    D.build_room()
    cc = pd.read_csv(D.ROOM / "creditcard.csv")
    cc.insert(0, "id", [f"FR{i:05d}" for i in range(1, len(cc) + 1)])
    split = np.where(np.random.default_rng(5).random(len(cc)) < 0.5, "test", "oot")
    idx_file = D.ROOM / "fr001_train_idx.csv"  # R's own split, saved by the redevelopment stage
    if train_rows is None and idx_file.exists():
        train_rows = pd.read_csv(idx_file)["row"].to_numpy()
    if train_rows is not None:
        split[np.asarray(train_rows) - 1] = "train"
    else:
        split = D._split(len(cc), 11)
    cc["split"] = split
    return cc


def _cr3_frame() -> pd.DataFrame:
    D.build_room()
    apps = pd.read_csv(D.ROOM / "applications_today.csv")
    sc = pd.read_csv(D.ROOM / "cr001_scores.csv")[["id", "pd", "decision"]]
    base = prepared()[["id", "split", "sex", "age_band"] + RAW_FEATURES]
    return base.merge(apps, on="id").merge(sc, on="id")


FRAMES: dict[str, Callable[[], pd.DataFrame]] = {
    "CR-001": _credit_frame, "CR-002": _credit_frame, "PR-001": _pr_frame, "FR-001": _fr_frame, "CR-003": _cr3_frame,
}


# ===================================================================== legacy output readers
def _rows_to_ids(df: pd.DataFrame, prefix: str, width: int) -> pd.Series:
    return df["row"].map(lambda r: f"{prefix}{int(r):0{width}d}")


def _cr2_legacy(work, room):
    s = pd.read_csv(work / "out" / "scores.csv")
    return pd.DataFrame({"id": _rows_to_ids(s, "GC", 4), "score": s["pd"]})


def _pr_legacy(work, room):
    s = pd.read_csv(work / "out" / "scores.csv")
    return pd.DataFrame({"id": _rows_to_ids(s, "PR", 5), "score": s["score"]})


def _fr_legacy(work, room):
    s = pd.read_csv(work / "out" / "scores.csv")
    return pd.DataFrame({"id": _rows_to_ids(s, "FR", 5), "score": s["score"],
                         "decision": np.where(s["score"] > 0.5, "ALERT", "PASS")})


def _cr3_legacy(work, room):
    s = pd.read_csv(work / "out" / "scores.csv")
    return pd.DataFrame({"id": s["id"], "score": s["limit"].astype(float)})


LEGACY_READERS = {"CR-002": _cr2_legacy, "PR-001": _pr_legacy, "FR-001": _fr_legacy, "CR-003": _cr3_legacy}


# ===================================================================== python runners → (model, scores, coef)
def _pr_py(mod, work, room):
    f = _pr_frame()
    m = mod.PR001FrequencyGLM().fit(f)
    return m, m.score(f), m.coef


def _fr_py(mod, work, room):
    idx = pd.read_csv(work / "out" / "train_idx.csv")["row"].to_numpy()
    pd.DataFrame({"row": idx}).to_csv(D.ROOM / "fr001_train_idx.csv", index=False)
    f = _fr_frame(idx)
    m = mod.FR001FraudGLM().fit(f, idx)
    return m, m.score(f), m.coef


def _cr3_py(mod, work, room):
    m = mod.CR003LimitStrategy()
    s = m.score(pd.read_csv(room / "applications_today.csv"), pd.read_csv(room / "cr001_scores.csv"))
    return m, s[["id", "score"]], None


PY_RUNNERS = {"PR-001": _pr_py, "FR-001": _fr_py, "CR-003": _cr3_py}


# ===================================================================== traffic pools + drift scenarios
def _cr_pool():
    d = prepared()
    return d[d["split"].isin(["test", "oot"])].reset_index(drop=True)


def _cr3_pool():
    d = _cr_pool()
    return d.merge(pd.read_csv(D.ROOM / "applications_today.csv"), on="id")


def _pr_pool():
    f = _pr_frame()
    return f[f["split"].isin(["test", "oot"])].reset_index(drop=True)


def _fr_pool():
    f = _fr_frame()
    return f[f["split"].isin(["test", "oot"])].reset_index(drop=True)


POOLS = {"CR-001": _cr_pool, "CR-003": _cr3_pool, "PR-001": _pr_pool, "FR-001": _fr_pool, "CR-002": _cr_pool}


def _credit_drift(r, scen, s, rng):
    r = r.astype({"credit.amount": float, "duration.in.month": float})
    if scen in ("affordability", "mixed"):
        r["credit.amount"] *= 1 + 1.5 * s
        r["duration.in.month"] += np.round(18 * s)
    if scen in ("checking", "mixed"):
        flip = rng.random(len(r)) < 0.6 * s
        r.loc[flip, "status.of.existing.checking.account"] = "... < 0 DM"
    if scen == "mixed":
        worsen = (r["creditability"] == "good") & (rng.random(len(r)) < 0.25 * s)
        r.loc[worsen, "creditability"] = "bad"
    return r


def _cr3_drift(r, scen, s, rng):
    if scen == "income_squeeze":
        r["income"] = np.round(r["income"] * (1 - 0.4 * s), -2)
        return r
    return _credit_drift(r, "affordability" if scen == "upstream_pd_drift" else scen, s, rng)


def _pr_drift(r, scen, s, rng):
    if scen == "young_drivers":
        m = rng.random(len(r)) < 0.6 * s
        r.loc[m, "agecat"] = rng.choice(["1", "2"], m.sum())
    elif scen == "urban_shift":
        m = rng.random(len(r)) < 0.6 * s
        r.loc[m, "area"] = "F"
    elif scen == "claims_spike":
        extra = rng.poisson(0.35 * s * r["exposure"].to_numpy())
        r["numclaims"] = r["numclaims"] + extra
    return r


def _fr_drift(r, scen, s, rng):
    if scen == "new_fraud_pattern":  # more fraud, and fraudsters that no longer look like the old pattern
        add = (r["Class"] == 0) & (rng.random(len(r)) < 0.02 * s)
        r.loc[add, "Class"] = 1
        f = r["Class"] == 1
        for v in ("V14", "V17", "V12", "V10"):
            r.loc[f, v] = r.loc[f, v] * (1 - s) + rng.normal(0, 1, f.sum()) * s
    elif scen == "amount_inflation":
        r["Amount"] = r["Amount"] * (1 + 2.0 * s)
    return r


DRIFTS = {"CR-001": _credit_drift, "CR-002": _credit_drift, "CR-003": _cr3_drift, "PR-001": _pr_drift, "FR-001": _fr_drift}


# ===================================================================== the estate
CREDIT_GROUPS = ["sex", "age_band"]
ADAPTERS: dict[str, Adapter] = {
    "CR-001": Adapter(
        id="CR-001", folder="cr001_pd_scorecard", script="cr001_scorecard.R", strategy="scorecard",
        spec=Spec("binary", "y", "approve", 0.35, CREDIT_GROUPS, RAW_FEATURES),
        reference=T / "cr001_model.py", class_name="CR001Scorecard",
        scenarios={"affordability": "loan amounts up, terms longer (cost-of-living squeeze)",
                   "checking": "more applicants with overdrawn checking accounts",
                   "mixed": "both, plus more defaults (outcome deterioration)"}),
    "CR-002": Adapter(
        id="CR-002", folder="cr002_rf_challenger", script="cr002_rf.R", strategy="rehost", epilogue="cr002.R",
        spec=Spec("binary", "y", "approve", 0.35, CREDIT_GROUPS, RAW_FEATURES + ["age.in.years"], trained_on_all=True),
        deployable=False, outputs=["out/scores.csv", "out/importance.csv"],
        code_findings=[
            ("high", "methodology", "Challenger trained and assessed on the same rows",
             "ranger() is fitted on 100% of the data and its PDs are in-sample; no hold-out or OOB evidence is used, so "
             "the challenger comparison with CR-001 overstates its power.", r"ranger\("),
            ("medium", "fairness", "Challenger uses age and personal status/sex directly",
             "bad ~ . pulls every column into the forest, including age.in.years and personal.status.and.sex.", r"bad ~ \."),
            ("low", "implementation", "Hardcoded shared-drive paths", "Reads and writes //shared/riskdata directly.", r"//shared")]),
    "CR-003": Adapter(
        id="CR-003", folder="cr003_limit_strategy", script="cr003_limits.R", strategy="translate", epilogue="cr003.R",
        spec=Spec("rules", None, "limit", None, CREDIT_GROUPS, ["income", "pd"]),
        reference=T / "cr003_model.py", class_name="CR003LimitStrategy",
        outputs=["out/scores.csv", "out/bands.csv"],
        contract="""Interface contract:
- class CR003LimitStrategy with method score(apps, scores) -> DataFrame with columns id, pd, band, score (the limit).
- apps has columns id, income; scores has columns id, pd, points, decision ('APPROVE'/'DECLINE').
- Reproduce R exactly: merge by id (sorted by id), PD bands with R cut() right-closed intervals
  (0,0.05],(0.05,0.10],(0.10,0.20],(0.20,0.35],(0.35,1] labelled A..E, income multipliers A .30 B .25 C .15 D .08 E 0,
  limit = min(round(income*mult, -2), 15000), and 0 when decision == 'DECLINE'. numpy/pandas only.""",
        code_findings=[
            ("high", "dependency", "Limits inherit every defect of CR-001",
             "Limits are a direct function of CR-001's PD and decision; CR-001 findings (cutoff, missing decisions) flow through.",
             r"cr001_scores"),
            ("medium", "governance", "Multipliers hardcoded from a 2019 strategy deck",
             "Income multipliers and the 15,000 cap are magic numbers with no approval record.", r"mult <- c\(")],
        scenarios={"income_squeeze": "applicant incomes fall (cost-of-living)",
                   "upstream_pd_drift": "CR-001's inputs drift, so PDs move and limits follow"}),
    "PR-001": Adapter(
        id="PR-001", folder="pr001_claims_glm", script="pr001_claims_freq.R", strategy="translate", epilogue="pr001.R",
        spec=Spec("frequency", "numclaims", "price", None, ["gender", "agecat"],
                  ["veh_body", "veh_age", "agecat", "area", "gender", "veh_value"], exposure="exposure", trained_on_all=True),
        reference=T / "pr001_model.py", class_name="PR001FrequencyGLM", outputs=["out/coef.csv", "out/scores.csv"],
        contract="""Interface contract:
- class PR001FrequencyGLM with fit(df) -> self, predict_frequency(df) -> numpy array (claims per unit exposure),
  score(df) -> DataFrame id, score, and property coef -> pandas Series named like R
  ('(Intercept)', 'veh_bodyCONVT', 'veh_age2', 'agecat2', 'areaB', 'genderM', ...).
- df has columns id, veh_value, exposure, clm, numclaims, claimcst0, veh_body, veh_age, gender, area, agecat.
- Reproduce R: rows with exposure > 0; Poisson GLM, log link, offset log(exposure); all five rating factors categorical with
  the alphabetically first level as reference (as R factor()). Use statsmodels (tol 1e-12) and numpy/pandas only.""",
        code_findings=[
            ("high", "fairness", "Gender used as a pricing factor",
             "The GLM rates on gender; gender-based insurance pricing has been prohibited in the UK/EU since December 2012 "
             "(EU Gender Directive, Test-Achats ruling).", r"\+ gender"),
            ("medium", "methodology", "No hold-out: fitted and assessed on all policies",
             "glm() is fitted on every policy and no validation sample or cross-validation is kept.", r"glm\("),
            ("low", "implementation", "Manual quarterly upload of the rate table", "Rate table reaches the pricing engine by hand.",
             r"manual upload")],
        scenarios={"young_drivers": "mix shifts to the youngest driver bands",
                   "urban_shift": "more policies from the highest-risk area F",
                   "claims_spike": "claim frequency rises (weather / inflation event)"}),
    "FR-001": Adapter(
        id="FR-001", folder="fr001_fraud", script="fr001_fraud.R", strategy="translate", epilogue="fr001.R",
        spec=Spec("binary", "Class", "alert", 0.5, [], ["V1", "V3", "V4", "V10", "V12", "V14", "V17", "Amount"]),
        reference=T / "fr001_model.py", class_name="FR001FraudGLM",
        outputs=["out/coef.csv", "out/scores.csv", "out/train_idx.csv"], extra_work_files=["creditcard.csv"],
        contract="""Interface contract:
- class FR001FraudGLM with fit(df, train_rows) -> self (train_rows = 1-based row numbers exported from R's sample()),
  predict_proba(df) -> numpy array, score(df) -> DataFrame id, score, decision ('ALERT' if p > 0.5 else 'PASS'),
  property coef -> pandas Series named '(Intercept)', 'V1', 'V3', 'V4', 'V10', 'V12', 'V14', 'V17', 'logamt'.
- df has columns id, Time, V1..V28, Amount, Class. logamt = log1p(Amount). Logistic GLM (statsmodels, tol 1e-12).""",
        code_findings=[
            ("high", "performance", "Alert threshold is untuned for a rare-event fraud rate",
             "The legacy code alerts at p > 0.5 although fraud is rare; most fraud scores below 0.5, so recall is low.",
             r"p > 0\.5"),
            ("medium", "data", "Development data not in the controlled estate",
             "creditcard.csv is a manual download; this factory validated a synthetic stand-in with the same schema.",
             r"creditcard\.csv")],
        scenarios={"new_fraud_pattern": "fraud rises and fraudsters stop matching the old pattern",
                   "amount_inflation": "transaction amounts inflate across the board"}),
}


def get(model_id: str) -> Adapter | None:
    return ADAPTERS.get(model_id)


def prepare_work(a: Adapter, work: Path) -> Path:
    """Fresh work dir + a private copy of the data room (legacy code may write into it)."""
    D.build_room()
    shutil.rmtree(work, ignore_errors=True)
    (work / "out").mkdir(parents=True)
    room = work / "riskdata"
    shutil.copytree(D.ROOM, room)
    for f in a.extra_work_files:
        shutil.copy(D.ROOM / f, work / f)
    return room
