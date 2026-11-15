"""Typed model knowledge: what agents write, humans approve, and the engine executes.

ModelSpec       what the model is and how to run it (one per model version)
ValidationPlan  which metrics decide pass / amber / red, with what thresholds
MonitoringPlan  live KPIs, alert rules, dashboard panels and drift scenarios

Column names in plans refer to the *scored frame*: the legacy export frame plus the standard columns
`score`, `decision`, `flag` (1 = adverse decision: decline / alert), `approve` (1 - flag), `split`
(train | test | oot), `occurred` (frequency models: target > 0), `missing_any`, and every derived group.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Task = Literal["binary", "frequency", "regression", "rules"]
Op = Literal[">", ">=", "<", "<="]


class _M(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ==================================================================== model spec
class InputMap(_M):
    ref: str = Field(description="Path exactly as the script or its arguments reference it, e.g. //shared/riskdata/x.csv or train.csv")
    asset: str = Field(description="Name of the data-room asset that provides it")


class GroupDef(_M):
    """A fairness / segment group derived from a frame column."""
    name: str = Field(description="Group column to create, e.g. age_band")
    column: str = Field(description="Source column in the frame")
    bins: Optional[list[float]] = Field(None, description="Numeric cut points (left-closed), e.g. [25] → <25, ≥25")
    labels: Optional[list[str]] = Field(None, description="Labels for the bins (len(bins)+1)")
    regex_map: Optional[dict[str, str]] = Field(None, description="Ordered {regex: label}; first match wins, e.g. {'^female': 'F', '.*': 'M'}")


class DecisionRule(_M):
    kind: Literal["approve", "alert", "price", "limit", "none"] = "none"
    op: Op = ">"
    cutoff: Optional[float] = Field(None, description="Adverse decision when score <op> cutoff")
    adverse_label: str = Field("", description="Decision label when adverse (DECLINE, ALERT…)")
    favourable_label: str = Field("", description="Decision label otherwise (APPROVE, PASS…)")


class Harness(_M):
    args: list[str] = Field(default_factory=list, description="Command-line arguments the batch job passes to the script")
    epilogue: str = Field("", description="Agent-written R run after the script to export the standard bundle")


class Upstream(_M):
    model_id: str
    via_asset: str = Field(description="Data-room asset the upstream model produces and this model reads")


class ModelSpec(_M):
    name: str = ""
    purpose: str = ""
    owner: str = ""
    model_type: str = Field("", description="Business type, e.g. Credit risk – PD scorecard")
    tier: Literal["A", "B", "C"] = "B"
    tier_rationale: str = ""
    entry_script: str = Field("", description="File name of the script the batch job runs")
    task: Task = "binary"
    strategy: Literal["translate", "rehost"] = Field("translate", description="translate = rebuild in Python with exact parity; rehost = validate the R outputs as-is")
    target: Optional[str] = Field(None, description="Outcome column in the frame (binary 0/1 or count)")
    exposure: Optional[str] = Field(None, description="Exposure column for frequency models")
    id_column: Optional[str] = Field(None, description="Row identifier column in the frame, if any")
    features: list[str] = Field(default_factory=list, description="Raw input columns the model uses")
    groups: list[GroupDef] = Field(default_factory=list)
    decision: DecisionRule = Field(default_factory=DecisionRule)
    inputs: list[InputMap] = Field(default_factory=list)
    harness: Harness = Field(default_factory=Harness)
    upstream: list[Upstream] = Field(default_factory=list)
    deployable: bool = True
    notes: list[str] = Field(default_factory=list)


# ==================================================================== validation plan
class Threshold(_M):
    op: Op = Field(description="Breach when value <op> limit, e.g. '>' for PSI, '<' for Gini")
    amber: Optional[float] = None
    red: Optional[float] = None


class Check(_M):
    id: str = Field(description="Stable id, e.g. perf.gini_oot")
    title: str
    category: Literal["performance", "calibration", "stability", "fairness", "data_quality", "policy", "implementation"]
    metric: str = Field(description="Metric catalog function")
    params: dict = Field(default_factory=dict, description="Recipe arguments (columns refer to the scored frame)")
    expand: Optional[Literal["features", "groups"]] = Field(None, description="Run once per feature (param col) or per group (param group)")
    threshold: Optional[Threshold] = None
    severity: Literal["high", "medium", "low"] = "medium"
    rationale: str = ""


class ValidationPlan(_M):
    checks: list[Check] = Field(default_factory=list)
    investigations: list[str] = Field(default_factory=list, description="Optional analyses worth running (challenger, slice_search, stress_test, fuzz)")
    rationale: str = ""


# ==================================================================== monitoring plan
class AlertRule(_M):
    id: str
    kpi: str
    op: Op
    threshold: float
    windows: int = Field(3, description="Consecutive breached windows before the alert fires")
    severity: Literal["amber", "red"] = "amber"
    action: Literal["notify", "revalidate"] = "notify"
    rationale: str = ""


class Panel(_M):
    id: str
    title: str
    kind: Literal["line", "area", "bar", "stat"] = "line"
    kpis: list[str]
    unit: str = ""


class Transform(_M):
    op: Literal["scale", "shift", "set_category", "flip_target", "null_rate"]
    column: str
    value: float | int | str = 0
    fraction: float = Field(1.0, description="Share of rows affected at full severity")


class Scenario(_M):
    id: str
    title: str
    description: str = ""
    transforms: list[Transform]


class MonitoringPlan(_M):
    kpis: list[str] = Field(default_factory=list)
    rules: list[AlertRule] = Field(default_factory=list)
    panels: list[Panel] = Field(default_factory=list)
    scenarios: list[Scenario] = Field(default_factory=list)
    rpm: int = 240
    rationale: str = ""
