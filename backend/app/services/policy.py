"""Policy library: reusable code-review rules applied to every legacy script (CRUD-managed in the DB).

Seeded once with sensible defaults; risk teams add, edit or disable rules from the Library page.
Model-specific issues are found by the LLM code review; these rules are the deterministic floor.
"""
from __future__ import annotations

import re

from app import repositories as repo
from app.domain.tables import PolicyCheck
from app.guardrails.injection import scan as injection_scan

DEFAULTS = [
    PolicyCheck(code="PC-01", title="Hardcoded file path", category="implementation", severity="low",
                pattern=r'"(?:[A-Za-z]:/|//|/Users/|/home/)[^"]+"',
                description="Reads or writes a fixed path (analyst laptop or shared drive) instead of controlled configuration."),
    PolicyCheck(code="PC-02", title="Hardcoded decision threshold", category="governance", severity="medium",
                pattern=r"(ifelse\([^)]*[<>]=?\s*0?\.\d+)|(\b\w+\s*[<>]=?\s*0\.\d+\s*(#|$))",
                description="A cut-off is coded as a literal; its approval and calibration evidence must be traceable."),
    PolicyCheck(code="PC-03", title="Missing values imputed as zero", category="data", severity="medium",
                pattern=r"is\.na\([^)]*\)\]\s*<-\s*0",
                description="Missing inputs silently become 0, which can change risk bands without anyone noticing."),
    PolicyCheck(code="PC-04", title="Stale TODO or temporary change", category="governance", severity="low",
                pattern=r"TODO|FIXME|never done|temporary",
                description="Outstanding work or 'temporary' changes left in production code."),
    PolicyCheck(code="PC-05", title="Protected characteristic used as a model input", category="fairness", severity="high",
                pattern=r"~[^#\n]*\b(gender|sex|race|ethnic\w*|religion|marital|personal\.status\w*)\b",
                description="The model formula uses a protected characteristic directly (e.g. gender-based pricing is prohibited in the UK/EU)."),
    PolicyCheck(code="PC-06", title="Model uses every column (`~ .`)", category="methodology", severity="medium",
                pattern=r"~\s*\.\s*[,)]",
                description="`y ~ .` pulls every column in, including identifiers and protected attributes, without review."),
    PolicyCheck(code="PC-07", title="Manual step in the production process", category="implementation", severity="low",
                pattern=r"\bmanual(ly)?\b",
                description="Outputs reach production through a manual step (upload, copy, re-key)."),
    PolicyCheck(code="PC-08", title="Instructions aimed at AI reviewers", category="security", severity="high", kind="injection",
                description="The file contains text that tries to steer automated reviewers. Treated as data and ignored."),
    PolicyCheck(code="PC-09", title="Comment contradicts code", category="governance", severity="high", kind="comment_code",
                description="A threshold stated in a comment differs from the value the code uses."),
]


def seed() -> None:
    for c in DEFAULTS:
        if repo.policy_checks.get(c.code) is None:
            repo.policy_checks.create(PolicyCheck(**c.model_dump()))  # fresh row (DEFAULTS stay detached)


def run(text: str, filename: str = "") -> list[dict]:
    """Apply every enabled rule; one hit per rule (first matching line), with line evidence."""
    lines = text.splitlines()
    hits: list[dict] = []
    for c in repo.policy_checks.list(enabled=True):
        line, code_text = None, ""
        if c.kind == "regex" and c.pattern:
            rx = re.compile(c.pattern, re.IGNORECASE)
            for i, l in enumerate(lines, 1):
                # rules about comments (TODOs, thresholds noted inline) see the whole line; the rest only code
                body = l if c.category in ("governance",) else l.split("#")[0]
                if rx.search(body):
                    line, code_text = i, l.strip()
                    break
        elif c.kind == "injection":
            inj = injection_scan(text)
            if inj:
                line, code_text = inj[0]["line"], inj[0]["text"]
        elif c.kind == "comment_code":
            cmt = re.search(r"#[^\n]*?(?:cut-?off|threshold)[^\n]*?(0\.\d+)", text, re.I)
            code_only = "\n".join(l.split("#")[0] for l in lines)
            code = re.search(r"[<>]=?\s*(0\.\d+)", code_only)
            if cmt and code and cmt.group(1) != code.group(1):
                line = code_only[:code.start()].count("\n") + 1
                code_text = f"comment says {cmt.group(1)}, code uses {code.group(1)}"
        if line:
            hits.append({"code": c.code, "title": c.title, "category": c.category, "severity": c.severity,
                         "description": c.description, "file": filename, "line": line, "text": code_text[:200]})
    return hits
