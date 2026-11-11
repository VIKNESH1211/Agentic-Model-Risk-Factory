"""Hash-chained, append-only audit ledger (build_plan.md §4.5)."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

from sqlmodel import select

from app.core.db import session
from app.core.events import _jsonable, bus
from app.domain.tables import LedgerEntry

GENESIS = "0" * 64
_lock = threading.Lock()


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _body(ts: float, actor: str, action: str, payload_hash: str) -> dict:
    return {"ts": ts, "actor": actor, "action": action, "payload_hash": payload_hash}


def payload_hash(payload: dict) -> str:
    return _h(json.dumps(payload, sort_keys=True))


def append(actor: str, action: str, payload: dict[str, Any] | None = None, *, emit: bool = True) -> LedgerEntry:
    payload = _jsonable(payload or {})
    with _lock, session() as s:
        last = s.exec(select(LedgerEntry).order_by(LedgerEntry.seq.desc()).limit(1)).first()
        prev = last.entry_hash if last else GENESIS
        ts = round(time.time(), 6)
        ph = payload_hash(payload)
        body = _body(ts, actor, action, ph)
        entry_hash = _h(prev + json.dumps(body, sort_keys=True))
        e = LedgerEntry(ts=ts, actor=actor, action=action, payload=payload,
                        payload_hash=ph, prev_hash=prev, entry_hash=entry_hash)
        s.add(e)
        s.commit()
        s.refresh(e)
    if emit:
        bus.publish("ledger_append", f"ledger #{e.seq} {action}", agent=actor,
                    run_id=str(payload.get("run_id", "")), model_id=str(payload.get("model_id", "")),
                    payload={"seq": e.seq, "action": action, "entry_hash": e.entry_hash})
    return e


def entries(limit: int | None = None, offset: int = 0) -> list[LedgerEntry]:
    with session() as s:
        q = select(LedgerEntry).order_by(LedgerEntry.seq).offset(offset)
        if limit:
            q = q.limit(limit)
        return list(s.exec(q).all())


def verify() -> dict:
    """Recompute every hash. Also re-hashes the stored payload, so editing a payload is caught."""
    prev = GENESIS
    n = 0
    for e in entries():
        n += 1
        body = _body(e.ts, e.actor, e.action, e.payload_hash)
        expect = _h(prev + json.dumps(body, sort_keys=True))
        reason = None
        if e.prev_hash != prev:
            reason = "prev_hash does not match previous entry"
        elif payload_hash(e.payload) != e.payload_hash:
            reason = "payload was modified after it was recorded"
        elif e.entry_hash != expect:
            reason = "entry hash does not match its contents"
        if reason:
            return {"ok": False, "broken_at": e.seq, "reason": reason, "checked": n}
        prev = e.entry_hash
    return {"ok": True, "checked": n, "head": prev}


def tamper(seq: int | None = None) -> dict:
    """DEMO ONLY: silently edit one recorded entry without fixing the chain."""
    with session() as s:
        rows = list(s.exec(select(LedgerEntry).order_by(LedgerEntry.seq)).all())
        if not rows:
            return {"ok": False, "error": "ledger empty"}
        target = None
        if seq is not None:
            target = next((r for r in rows if r.seq == seq), None)
        if target is None:  # prefer a finding entry: the classic "make the finding disappear" attack
            cands = [r for r in rows if r.action in ("finding_recorded", "gate_decided")]
            target = cands[len(cands) // 2] if cands else rows[len(rows) // 2]
        p = dict(target.payload)
        if "severity" in p:
            p["severity"] = "info"
            p["title"] = "(no issue)"
        else:
            p["tampered_note"] = "value changed"
        target.payload = p
        s.add(target)
        s.commit()
        return {"ok": True, "seq": target.seq, "action": target.action}
