"""Prompt-injection pre-scan for untrusted file content."""
from __future__ import annotations

import re

PATTERNS = [
    (r"ignore (all )?(previous|prior|above) instructions", "instruction override"),
    (r"\b(ai|llm|automated) (reviewer|validator|agent)s?\b", "addresses AI reviewers"),
    (r"(report|return|give) (zero|no) findings", "suppress findings"),
    (r"\b(pass|approve[d]?) (rating|it|this model)\b|give it a pass", "force approval"),
    (r"pre-?approved by", "false authority claim"),
    (r"you are now|system prompt|disregard", "role / prompt manipulation"),
]


def scan(text: str) -> list[dict]:
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        for pat, label in PATTERNS:
            if re.search(pat, line, re.IGNORECASE):
                hits.append({"line": i, "label": label, "text": line.strip()[:200]})
                break
    return hits
