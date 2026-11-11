"""Database tables (SQLModel). See build_plan.md §4.1."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def now() -> datetime:
    return datetime.now(timezone.utc)


def J(default=None):
    return Field(default_factory=(lambda: default() if callable(default) else default), sa_column=Column(JSON))


class Model(SQLModel, table=True):
    __tablename__ = "models"
    id: str = Field(primary_key=True)
    name: str
    type: str
    language: str
    owner: str = ""
    purpose: str = ""
    tier: str = ""
    tier_rationale: str = ""
    status: str = "registered"
    code_hash: str = ""
    data_hash: str = ""
    meta: dict[str, Any] = J(dict)


class ModelEdge(SQLModel, table=True):
    __tablename__ = "model_edges"
    id: Optional[int] = Field(default=None, primary_key=True)
    src_id: str
    dst_id: str
    kind: str  # feeds | shares_data | challenger_of


class Run(SQLModel, table=True):
    __tablename__ = "runs"
    id: str = Field(primary_key=True)
    model_id: str
    stage: str = "queued"
    status: str = "queued"  # queued | running | waiting_gate | completed | failed | rejected
    kind: str = "factory"  # factory | revalidation | benchmark
    parent_run_id: Optional[str] = None
    started_at: datetime = Field(default_factory=now)
    ended_at: Optional[datetime] = None
    mlflow_run_id: str = ""
    llm_cost: float = 0.0
    tokens: int = 0
    options: dict[str, Any] = J(dict)
    state: dict[str, Any] = J(dict)


class Artifact(SQLModel, table=True):
    __tablename__ = "artifacts"
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str
    kind: str
    path: str
    sha256: str
    created_at: datetime = Field(default_factory=now)


class Metric(SQLModel, table=True):
    __tablename__ = "metrics"
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    name: str = Field(index=True)
    value: float
    split: str = ""
    slice: str = ""
    definition: str = ""
    recipe: dict[str, Any] = J(dict)
    code_hash: str = ""
    data_hash: str = ""
    ledger_seq: Optional[int] = None
    created_at: datetime = Field(default_factory=now)


class Finding(SQLModel, table=True):
    __tablename__ = "findings"
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = ""
    model_id: str
    run_id: str
    severity: str  # high | medium | low | info
    category: str
    title: str
    detail: str = ""
    detector: str = ""
    impact: dict[str, Any] = J(dict)
    status: str = "open"
    evidence: dict[str, Any] = J(dict)


class Gate(SQLModel, table=True):
    __tablename__ = "gates"
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str
    model_id: str = ""
    stage: str
    status: str = "pending"  # pending | approved | rejected | changes_requested
    title: str = ""
    context: dict[str, Any] = J(dict)
    decided_by: str = ""
    decision: str = ""
    comment: str = ""
    requested_at: datetime = Field(default_factory=now)
    decided_at: Optional[datetime] = None


class Control(SQLModel, table=True):
    __tablename__ = "controls"
    ref: str = Field(primary_key=True)
    principle: str
    title: str
    description: str


class ControlResult(SQLModel, table=True):
    __tablename__ = "control_results"
    id: Optional[int] = Field(default=None, primary_key=True)
    ref: str
    model_id: str
    status: str  # pass | warn | fail | n/a
    evidence: dict[str, Any] = J(dict)
    checked_at: datetime = Field(default_factory=now)


class LedgerEntry(SQLModel, table=True):
    __tablename__ = "ledger"
    seq: Optional[int] = Field(default=None, primary_key=True)
    ts: float
    actor: str
    action: str
    payload: dict[str, Any] = J(dict)
    payload_hash: str
    prev_hash: str
    entry_hash: str


class Benchmark(SQLModel, table=True):
    __tablename__ = "benchmarks"
    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: str
    defect_type: str
    variant_id: str
    title: str = ""
    expected_detector: str = ""
    detected: bool = False
    detector: str = ""
    severity: str = ""
    false_alarm: bool = False
    detail: dict[str, Any] = J(dict)


class MonitorBatch(SQLModel, table=True):
    __tablename__ = "monitor_batches"
    id: Optional[int] = Field(default=None, primary_key=True)
    model_id: str
    label: str
    severity: float = 0.0
    feature_set: str = ""
    psi: float = 0.0
    csi: dict[str, Any] = J(dict)
    perf: dict[str, Any] = J(dict)
    status: str = "green"
    revalidation_run_id: Optional[str] = None
    created_at: datetime = Field(default_factory=now)


class Report(SQLModel, table=True):
    __tablename__ = "reports"
    id: str = Field(primary_key=True)
    run_id: str
    model_id: str
    version: int = 1
    title: str = ""
    markdown: str = ""
    status: str = "draft"
    checker: dict[str, Any] = J(dict)
    created_at: datetime = Field(default_factory=now)


class EventRow(SQLModel, table=True):
    __tablename__ = "events"
    id: str = Field(primary_key=True)
    ts: str
    run_id: str = ""
    model_id: str = ""
    stage: str = ""
    agent: str = ""
    type: str
    summary: str
    payload: dict[str, Any] = J(dict)


class LLMCall(SQLModel, table=True):
    __tablename__ = "llm_calls"
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = ""
    agent: str = ""
    task: str = ""
    source: str = ""  # live | cache | offline
    prompt_hash: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    flagged: bool = False
    created_at: datetime = Field(default_factory=now)


class AgentStep(SQLModel, table=True):
    """Persisted agent trace: plan, thoughts, tool calls with arguments and results, observations, decisions."""
    __tablename__ = "agent_steps"
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    model_id: str = ""
    stage: str = ""
    agent: str = ""
    kind: str  # plan | thought | tool_call | tool_result | observation | decision | error
    title: str = ""
    content: dict[str, Any] = J(dict)
    ts: datetime = Field(default_factory=now)
    duration_ms: Optional[int] = None


class MonitorWindow(SQLModel, table=True):
    """One 10-second window of live (simulated) traffic KPIs for a deployed model."""
    __tablename__ = "monitor_windows"
    id: Optional[int] = Field(default=None, primary_key=True)
    model_id: str = Field(index=True)
    ts: datetime = Field(default_factory=now)
    kpis: dict[str, Any] = J(dict)
    status: str = "green"


class MonitorAlert(SQLModel, table=True):
    __tablename__ = "monitor_alerts"
    id: Optional[int] = Field(default=None, primary_key=True)
    model_id: str = Field(index=True)
    ts: datetime = Field(default_factory=now)
    rule: str
    severity: str  # amber | red
    message: str
    value: float = 0.0
    action: str = ""
    revalidation_run_id: Optional[str] = None
    resolved: bool = False


class AppSetting(SQLModel, table=True):
    __tablename__ = "app_settings"
    key: str = Field(primary_key=True)
    value: dict[str, Any] = J(dict)
