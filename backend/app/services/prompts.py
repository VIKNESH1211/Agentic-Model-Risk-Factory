"""Prompt registry: every prompt the agents send lives in the DB, versioned and editable (Library page).

Templates use {{name}} placeholders (plain identifiers only, so evidence tokens like {{m:run:metric}} and R code
with `$` pass through untouched). Defaults are seeded from app/agents/prompts/defaults.py; editing a prompt
adds a version, and the newest version is the one agents use. Note: the LLM cache keys on the rendered text,
so an edited prompt is a cache miss.
"""
from __future__ import annotations

import re
import threading

from app import repositories as repo
from app.agents.prompts.defaults import DEFAULTS
from app.domain.tables import PromptTemplate
from app.evidence import ledger

VAR = re.compile(r"\{\{([a-z_][a-z0-9_]*)\}\}")
_cache: dict[str, str] = {}
_lock = threading.Lock()


def seed() -> None:
    """Insert missing prompts; prompts never edited by a person follow the defaults shipped with the code."""
    for key, (desc, text) in DEFAULTS.items():
        rows = repo.prompts.list(key=key)
        if not rows:
            repo.prompts.create(PromptTemplate(key=key, version=1, text=text, description=desc, author="system"))
            continue
        cur = max(rows, key=lambda r: r.version)
        if cur.author == "system" and cur.text != text:
            repo.prompts.create(PromptTemplate(key=key, version=cur.version + 1, text=text, description=desc, author="system"))
    _cache.clear()


def active(key: str) -> PromptTemplate:
    rows = repo.prompts.list(key=key)
    if not rows:
        seed()
        rows = repo.prompts.list(key=key)
    return max(rows, key=lambda r: r.version)


def text(key: str) -> str:
    with _lock:
        if key not in _cache:
            _cache[key] = active(key).text
        return _cache[key]


def variables(template: str) -> list[str]:
    return sorted(set(VAR.findall(template)))


def render(key: str, **vars) -> str:
    t = text(key)
    missing = [v for v in variables(t) if v not in vars]
    if missing:
        raise KeyError(f"prompt '{key}' needs {missing}")
    return VAR.sub(lambda m: str(vars[m.group(1)]), t)


def update(key: str, new_text: str, author: str) -> PromptTemplate:
    cur = active(key)
    lost = set(variables(cur.text)) - set(variables(new_text))
    if lost:
        raise ValueError(f"the new text drops placeholder(s) the agent fills in: {sorted(lost)}")
    row = repo.prompts.create(PromptTemplate(key=key, version=cur.version + 1, text=new_text,
                                             description=cur.description, author=author))
    with _lock:
        _cache.pop(key, None)
    ledger.append("human", "prompt_updated", {"key": key, "version": row.version, "by": author})
    return row


def reset(key: str, author: str) -> PromptTemplate:
    return update(key, DEFAULTS[key][1], author)


def catalog() -> list[dict]:
    out = []
    for key in DEFAULTS:
        a = active(key)
        out.append({"key": key, "version": a.version, "description": a.description, "author": a.author,
                    "updated_at": a.created_at.isoformat(), "variables": variables(a.text), "text": a.text,
                    "is_default": a.text == DEFAULTS[key][1]})
    return out
