"""Thin LLM adapter with record/replay cache (build_plan.md §4.8).

LLM_MODE:
  live    -> call the provider every time
  record  -> call the provider and save the response to demo/llm_cache/
  replay  -> use demo/llm_cache/ if present; otherwise use the deterministic offline drafter

LLM_PROVIDER=offline never calls a network service: every call uses the caller's
deterministic `fallback`, which is how the demo runs with no API key.
Untrusted file content must be passed via `untrusted=` so it is wrapped and labelled as data.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable

from app.core.config import settings
from app.core.db import save
from app.domain.tables import LLMCall

PRICES = {  # USD per 1M tokens (input, output)
    "gpt-4o-mini": (0.15, 0.60),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}



@dataclass
class LLMResult:
    data: dict
    source: str  # live | cache | offline
    tokens: int = 0
    cost: float = 0.0


LAST_ERROR: dict = {}

from app.core import logging as _mlog  # noqa: E402

_log = _mlog.get("llm")


class BudgetExceeded(RuntimeError):
    pass


def _system() -> str:
    from app.services import prompts  # the system prompt is editable like every other prompt
    return prompts.text("system_guard")


def _key(task: str, prompt: str, model: str) -> str:
    return hashlib.sha256(f"{model}\n{task}\n{prompt}".encode()).hexdigest()[:32]


def wrap_untrusted(name: str, content: str) -> str:
    content = content.replace("</untrusted_data>", "&lt;/untrusted_data&gt;")
    return f'<untrusted_data source="{name}">\n{content}\n</untrusted_data>'


def complete_json(task: str, prompt: str, schema: dict, fallback: Callable[[], dict], *,
                  run_id: str = "", agent: str = "", untrusted: dict[str, str] | None = None,
                  spent: dict | None = None, fast: bool = False) -> LLMResult:
    """Ask for a JSON object matching `schema`. `fallback` must return the same shape deterministically.
    fast=True uses the cheaper model (agent plans and reflections)."""
    full_prompt = prompt
    for name, content in (untrusted or {}).items():
        full_prompt += "\n\n" + wrap_untrusted(name, content)
    model = (settings.llm_fast_model or settings.llm_model) if fast else settings.llm_model
    k = _key(task, full_prompt, model)
    cache_file = settings.llm_cache_dir / f"{task}_{k}.json"

    result: LLMResult | None = None
    if settings.llm_mode == "replay" and cache_file.exists():
        result = LLMResult(json.loads(cache_file.read_text())["data"], "cache")
    elif settings.llm_provider in ("openai", "anthropic", "groq") and settings.llm_mode in ("live", "record", "replay"):
        if spent is not None and spent.get("cost", 0) >= settings.max_run_cost:
            raise BudgetExceeded(f"run cost cap ${settings.max_run_cost} reached")
        try:
            call = {"openai": _call_openai, "groq": _call_groq}.get(settings.llm_provider, _call_anthropic)
            result = call(model, full_prompt, schema)
            LAST_ERROR.clear()
            if settings.llm_mode in ("record", "replay"):
                settings.llm_cache_dir.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps({"task": task, "model": model, "data": result.data}, indent=2))
        except BudgetExceeded:
            raise
        except Exception as e:  # provider down / no key: degrade to offline drafter, never break the demo
            msg = getattr(e, "message", None) or str(e)
            status = getattr(e, "status_code", "")
            LAST_ERROR.update({"type": type(e).__name__, "message": msg[:300]})
            result = LLMResult(fallback(), f"offline (provider error: {type(e).__name__} {status} {msg[:160]})".strip())
    if result is None:
        result = LLMResult(fallback(), "offline")

    if spent is not None:
        spent["cost"] = spent.get("cost", 0) + result.cost
        spent["tokens"] = spent.get("tokens", 0) + result.tokens
    _log.info("llm %-22s %-6s %s tokens=%s cost=$%.5f", task[:22], agent[:6], result.source[:60], result.tokens, result.cost,
              extra={"run_id": run_id, "agent": agent})
    save(LLMCall(run_id=run_id, agent=agent, task=task, source=result.source, prompt_hash=k,
                 tokens_in=0, tokens_out=result.tokens, cost=result.cost))
    return result


def _call_anthropic(model: str, prompt: str, schema: dict) -> LLMResult:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.llm_api_key or None, timeout=120.0)
    kwargs: dict[str, Any] = dict(
        model=model, max_tokens=16000, system=_system(),
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": prompt}],
    )
    try:  # server-side refusal fallback (beta); retry plainly if this account/model rejects it
        resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
    except anthropic.BadRequestError:
        resp = client.messages.create(**kwargs)
    if resp.stop_reason == "refusal":
        raise RuntimeError("model refused")
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    data = json.loads(text)
    pin, pout = PRICES.get(model, (4.0, 20.0))
    tin, tout = resp.usage.input_tokens, resp.usage.output_tokens
    return LLMResult(data, "live", tin + tout, (tin * pin + tout * pout) / 1e6)


def _validate(data: dict, schema: dict) -> dict:
    """Light check that the JSON has the required keys with the right basic types."""
    if not isinstance(data, dict):
        raise ValueError("model did not return a JSON object")
    types = {"string": str, "boolean": bool, "array": list, "object": dict, "number": (int, float)}
    for k in schema.get("required", []):
        if k not in data:
            raise ValueError(f"missing key '{k}' in model JSON")
        t = schema.get("properties", {}).get(k, {}).get("type")
        if t in types and not isinstance(data[k], types[t]):
            raise ValueError(f"key '{k}' should be {t}")
    for k, prop in schema.get("properties", {}).items():
        if k in data and k not in schema.get("required", []) and data[k] in ("", None):
            del data[k]  # an empty optional field is the same as an absent one
            continue
        if k in data and "enum" in prop and data[k] not in prop["enum"]:
            match = next((e for e in prop["enum"] if isinstance(data[k], str) and e.lower() == data[k].strip().lower()), None)
            if match is None:
                raise ValueError(f"key '{k}' must be one of {prop['enum']}")
            data[k] = match
    if schema.get("additionalProperties") is False:  # drop extra keys; optional keys may be absent
        return {k: data[k] for k in schema.get("properties", {}) if k in data}
    return data


import threading as _threading

_GROQ_LOCK = _threading.Lock()  # free tier has a small tokens-per-minute budget: one call at a time


def _call_groq(model: str, prompt: str, schema: dict) -> LLMResult:
    """Groq (free tier): one call at a time; on a rate limit wait as asked (≤60s) and retry twice."""
    import time as _time

    from groq import RateLimitError

    from groq import APIStatusError

    max_tokens = 8000
    with _GROQ_LOCK:
        for attempt in range(4):
            try:
                return _groq_once(model, prompt, schema, max_tokens)
            except RateLimitError as e:
                if attempt == 2:
                    raise
                ra = e.response.headers.get("retry-after") if getattr(e, "response", None) is not None else None
                wait = min(float(ra) if ra else 20.0 * (attempt + 1), 60.0)
                LAST_ERROR.update({"type": "RateLimitError", "message": f"Groq rate limit – waiting {wait:.0f}s and retrying"})
                _time.sleep(wait)
            except APIStatusError as e:  # 413: requested tokens exceed the per-minute budget; 5xx: provider hiccup
                if attempt == 3 or not (e.status_code == 413 or e.status_code >= 500):
                    raise
                if e.status_code == 413:
                    max_tokens = max(2500, max_tokens // 2)
                _time.sleep(8 * (attempt + 1))
    raise RuntimeError("groq: retries exhausted")


def _groq_once(model: str, prompt: str, schema: dict, max_tokens: int = 8000) -> LLMResult:
    from groq import Groq

    client = Groq(api_key=settings.groq_api_key or None, timeout=120.0, max_retries=1)
    system = _system() + (" Respond with a single JSON object only, matching this JSON Schema exactly "
                             "(all required keys, no extra keys): " + json.dumps(schema))
    from groq import BadRequestError

    last_err: Exception | None = None
    for _ in range(3):  # retry if the model's JSON is malformed (Groq rejects it as json_validate_failed) or incomplete
        try:
            resp = client.chat.completions.create(
                model=model, temperature=0.2, max_completion_tokens=max_tokens,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            )
        except BadRequestError as e:
            if "json_validate_failed" in str(e) or "json" in str(e).lower():
                last_err = e
                continue
            raise
        try:
            data = _validate(json.loads(resp.choices[0].message.content or "{}"), schema)
            u = resp.usage
            return LLMResult(data, "live", (u.prompt_tokens + u.completion_tokens) if u else 0, 0.0)  # free tier
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
    raise last_err or RuntimeError("groq: no valid JSON")


# ---------------------------------------------------------------- OpenAI over plain HTTPS (no SDK)
def _call_openai(model: str, prompt: str, schema: dict) -> LLMResult:
    """POST /v1/chat/completions in JSON mode. Retries rate limits / server errors (honouring retry-after) and
    malformed or incomplete JSON; the reply is checked against the schema's required keys."""
    import time as _time

    import httpx

    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    url = f"{settings.openai_base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"}
    system = _system() + (" Respond with a single JSON object only, matching this JSON Schema exactly "
                          "(all required keys, no extra keys): " + json.dumps(schema))
    body = {"model": model, "temperature": 0.2, "max_tokens": 12000, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
    last_err: Exception | None = None
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=15.0)) as client:
        for attempt in range(5):
            try:
                r = client.post(url, headers=headers, json=body)
            except httpx.TransportError as e:  # network hiccup
                last_err = e
                _time.sleep(3 * (attempt + 1))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                ra = r.headers.get("retry-after")
                wait = min(float(ra) if ra and ra.replace(".", "", 1).isdigit() else 5.0 * (attempt + 1), 60.0)
                LAST_ERROR.update({"type": f"HTTP {r.status_code}", "message": f"OpenAI {r.status_code} – retrying in {wait:.0f}s"})
                last_err = RuntimeError(f"OpenAI HTTP {r.status_code}: {r.text[:200]}")
                _time.sleep(wait)
                continue
            if r.status_code != 200:
                raise RuntimeError(f"OpenAI HTTP {r.status_code}: {r.text[:300]}")
            data = r.json()
            choice = data["choices"][0]
            u = data.get("usage") or {}
            try:
                if choice.get("finish_reason") == "length":
                    raise ValueError("reply cut off at the token limit")
                parsed = _validate(json.loads(choice["message"].get("content") or "{}"), schema)
            except (ValueError, json.JSONDecodeError) as e:
                last_err = e
                continue
            tin, tout = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
            pin, pout = PRICES.get(model, (0.15, 0.60))
            return LLMResult(parsed, "live", tin + tout, (tin * pin + tout * pout) / 1e6)
    raise last_err or RuntimeError("openai: no valid JSON")
