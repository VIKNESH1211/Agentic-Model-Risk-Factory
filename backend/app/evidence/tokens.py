"""Number tokens: {{m:<run_id>:<metric>}} resolver + unsourced-number checker."""
from __future__ import annotations

import math
import re

from app.evidence import metric_store

TOKEN_RE = re.compile(r"\{\{(m:[A-Za-z0-9_\-]+:[A-Za-z0-9_.\-=]+)\}\}")
# Any digit sequence that is not inside a token. Allow-list handled in check().
NUM_RE = re.compile(r"(?<![A-Za-z_\-])[-+]?\d[\d,]*(?:\.\d+)?%?")
ALLOWED_PATTERNS = [
    re.compile(r"^#{1,6}\s+\d+(\.\d+)*\.?\s"),            # numbered headings: "## 3. Performance"
]
ALLOWED_TOKENS_IN_TEXT = re.compile(  # model ids, finding codes, run ids, years, rule refs
    r"(SS1/23|CR-\d{3}|PR-\d{3}|FR-\d{3}|F-\d{2}|run_[a-z0-9]+|Tier [ABC]|\b(19|20)\d{2}\b|\bP[1-5]\b|1e-\d+)",
    re.IGNORECASE,
)


def parse(token: str) -> tuple[str, str]:
    _, run_id, name = token.split(":", 2)
    return run_id, name


def fmt(name: str, v: float) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    base = name.split(".")[0]
    if base in {"approval_rate", "bad_rate", "rate_true", "decision_agreement", "dup_rate", "missing_rate"} or name.endswith("_pct"):
        return f"{v * 100:.1f}%"
    if base in {"count_true", "decision_flips", "fuzz_rows", "fuzz_divergences", "fuzz_legacy_na",
                "n", "rows", "findings"} or name.startswith("count.") or name.startswith("n."):
        return f"{int(round(v)):,}"
    if base in {"parity", "coef_max_abs_diff", "score_max_abs_diff"} or (v != 0 and abs(v) < 1e-3):
        return f"{v:.2e}"
    if base == "runtime_s":
        return f"{v:.1f}s"
    if base == "el_gap" or name.startswith("assumption.avg_ead") or name.startswith("assumption.annual"):
        return f"{v:,.0f}"
    if base == "llm_cost":
        return f"${v:.2f}"
    return f"{v:.3f}"


def resolve(markdown: str) -> tuple[str, dict[str, dict]]:
    """Return markdown unchanged plus a map token -> {value, display, ok}."""
    out: dict[str, dict] = {}
    for tok in TOKEN_RE.findall(markdown):
        run_id, name = parse(tok)
        m = metric_store.get(run_id, name)
        out[tok] = ({"value": m.value, "display": fmt(name, m.value), "ok": True, "metric_id": m.id,
                     "definition": m.definition} if m else {"value": None, "display": "⟨missing⟩", "ok": False})
    return markdown, out


def check(markdown: str) -> dict:
    """Reject drafts containing literal numeric claims outside tokens."""
    violations = []
    unknown = []
    for i, line in enumerate(markdown.splitlines(), 1):
        if any(p.match(line) for p in ALLOWED_PATTERNS):
            line = re.sub(r"^#{1,6}\s+\d+(\.\d+)*\.?", "", line)
        stripped = TOKEN_RE.sub("", line)
        stripped = ALLOWED_TOKENS_IN_TEXT.sub("", stripped)
        stripped = re.sub(r"`[^`]*`", "", stripped)  # inline code (identifiers, file names)
        if re.match(r"^\s*\|?\s*[-:| ]+\|?\s*$", stripped):  # table separator
            continue
        for mt in NUM_RE.finditer(stripped):
            violations.append({"line": i, "text": mt.group(0), "context": line.strip()[:120]})
    for tok in TOKEN_RE.findall(markdown):
        run_id, name = parse(tok)
        if metric_store.get(run_id, name) is None:
            unknown.append(tok)
    return {"ok": not violations and not unknown, "violations": violations, "unknown_tokens": unknown,
            "token_count": len(TOKEN_RE.findall(markdown))}
