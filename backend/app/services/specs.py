"""Model specifications: draft (agent or human) → lint → approve. The engine only ever reads them from here."""
from __future__ import annotations

from pydantic import ValidationError

from app import repositories as repo
from app.core.events import bus
from app.domain.schemas import ModelSpec
from app.domain.tables import SpecVersion
from app.engine.parity import CONTRACT as PY_CONTRACT
from app.evidence import ledger
from app.services import onboarding, prompts


class SpecError(ValueError):
    pass


def parse(body: dict | ModelSpec) -> ModelSpec:
    if isinstance(body, ModelSpec):
        return body
    try:
        return ModelSpec.model_validate(body)
    except ValidationError as e:
        raise SpecError("; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:8])) from e


def current(model_id: str) -> ModelSpec:
    row = repo.specs.current(model_id)
    if row is None:
        raise SpecError(f"{model_id} has no specification yet — run intake first")
    return ModelSpec.model_validate(row.body)


def current_or_none(model_id: str) -> ModelSpec | None:
    row = repo.specs.current(model_id)
    return ModelSpec.model_validate(row.body) if row else None


FITTED = ("glm", "lm", "ranger", "randomForest", "gbm", "xgb", "train", "nnet", "svm", "rpart")
NOT_PORTABLE = ("ranger", "randomForest", "gbm", "xgb", "nnet", "svm")


def lint(model_id: str, spec: ModelSpec, probe_columns: set[str] | None = None, probe_objects: list[dict] | None = None) -> list[str]:
    """Deterministic checks a spec must pass before the engine can use it."""
    errs: list[str] = []
    if probe_objects is not None:
        classes = " ".join(o.get("class", "") for o in probe_objects)
        fitted = any(k in classes.split("/") or k in classes for k in FITTED)
        if not fitted and spec.task in ("binary", "frequency", "regression"):
            errs.append(f"task '{spec.task}' but the script fits no statistical model (no glm/lm/forest object): use task 'rules'")
        if any(k in classes for k in NOT_PORTABLE) and spec.strategy == "translate":
            errs.append("the script fits a tree ensemble / ML model that cannot be reproduced exactly outside R: use strategy 'rehost'")
        only_glm = fitted and not any(k in classes for k in NOT_PORTABLE)
        if spec.strategy == "rehost" and (only_glm or not fitted):
            errs.append("this model (GLM/LM or plain rules) can be reproduced exactly in Python: use strategy 'translate' "
                        "(rehost is only for tree ensembles / ML models that cannot be ported)")
    if spec.task == "rules" and spec.target:
        errs.append(f"rules models have no outcome to predict: set target to null ('{spec.target}' is the model's output, not an outcome)")
    files = {f.name for f in onboarding.files_of(model_id, "script")}
    if spec.entry_script not in files:
        errs.append(f"entry_script '{spec.entry_script}' is not an uploaded script ({', '.join(sorted(files))})")
    for m in spec.inputs:
        if repo.current_asset(m.asset) is None:
            errs.append(f"input '{m.ref}' maps to asset '{m.asset}', which is not in the data room")
    if probe_columns is not None:
        for col, what in [(spec.target, "target"), (spec.exposure, "exposure"), (spec.id_column, "id_column")]:
            if col and col not in probe_columns:
                errs.append(f"{what} '{col}' is not a column of any data frame the script creates")
        missing = [f for f in spec.features if f not in probe_columns]
        if missing:
            errs.append(f"features not found in the script's data frames: {missing[:8]}")
        for g in spec.groups:
            if g.column not in probe_columns:
                errs.append(f"group '{g.name}' derives from '{g.column}', which is not a column")
    for g in spec.groups:
        if g.bins and g.labels and len(g.labels) != len(g.bins) + 1:
            errs.append(f"group '{g.name}': {len(g.bins)} bins need {len(g.bins) + 1} labels")
    if spec.decision.kind in ("approve", "alert") and spec.decision.cutoff is None and not spec.decision.adverse_label:
        errs.append("decision kind needs a cutoff or the coded adverse label")
    if spec.task == "frequency" and not spec.exposure:
        errs.append("frequency models need an exposure column (use a column of 1s only if the code has no exposure)")
    if not spec.features:
        errs.append("features is empty")
    return errs


def autofix(spec: ModelSpec, script: str) -> tuple[ModelSpec, list[str]]:
    """Deterministic repairs of mechanical LLM slips (each one is reported, nothing is silent)."""
    fixes: list[str] = []
    text = script + " " + " ".join(spec.harness.args)
    keep = []
    for m in spec.inputs:
        if repo.current_asset(m.asset) is None and m.ref not in text:
            fixes.append(f"dropped input '{m.ref}' → '{m.asset}': the script never reads it (package data such as data(x) is not an input)")
        else:
            keep.append(m)
    spec.inputs = keep
    for g in spec.groups:
        if g.bins and g.labels and len(g.labels) != len(g.bins) + 1:
            fixes.append(f"group '{g.name}': {len(g.labels)} labels for {len(g.bins)} cut points — labels regenerated")
            g.labels = None
    seen = set()
    feats = [f for f in spec.features if not (f in seen or seen.add(f))]
    if len(feats) != len(spec.features):
        fixes.append("duplicate features removed")
        spec.features = feats
    return spec, fixes


def contract(model_id: str, spec: ModelSpec) -> str:
    d = spec.decision
    return prompts.render(
        "contract", model_id=model_id, name=spec.name or model_id, entry_script=spec.entry_script,
        args=" ".join(spec.harness.args), inputs=", ".join(f"{m.ref} ← {m.asset}" for m in spec.inputs) or "nothing from the data room",
        coef=" · coef.csv" if spec.task in ("binary", "frequency", "regression") else "",
        train=" · train_rows.csv (if fitted on a subset)", task=spec.task, target=spec.target or "—",
        exposure=spec.exposure or "—", strategy=spec.strategy, features=", ".join(spec.features) or "—",
        decision=(f"{d.kind}: {d.adverse_label or 'adverse'} when score {d.op} {d.cutoff}" if d.cutoff is not None
                  else d.kind),
        groups=", ".join(f"{g.name} (from {g.column})" for g in spec.groups) or "none",
        python_contract=PY_CONTRACT)


def save_draft(model_id: str, body: dict | ModelSpec, author: str, note: str = "") -> SpecVersion:
    spec = parse(body)
    row = repo.specs.add_version(model_id, spec.model_dump(), author, note, contract=contract(model_id, spec))
    _sync_model(model_id, spec)
    ledger.append(author.split(":")[0] if ":" in author else "human", "spec_drafted",
                  {"model_id": model_id, "version": row.version, "author": author})
    bus.publish("info", f"{model_id}: spec v{row.version} drafted by {author}", model_id=model_id, agent=author.split(":")[-1])
    return row


def approve(model_id: str, by: str) -> SpecVersion | None:
    row = repo.specs.latest(model_id)
    if row is None or row.status == "approved":
        return row
    row = repo.specs.approve(row.id, by)
    ledger.append("human", "spec_approved", {"model_id": model_id, "version": row.version, "by": by})
    return row


def _sync_model(model_id: str, spec: ModelSpec) -> None:
    """Keep the inventory row in step with the spec (name, type, tier…)."""
    m = repo.models.get(model_id)
    if m is None:
        return
    repo.models.update(model_id, name=spec.name or m.name, type=spec.model_type or m.type, owner=spec.owner or m.owner,
                       purpose=spec.purpose or m.purpose, tier=spec.tier, tier_rationale=spec.tier_rationale)
