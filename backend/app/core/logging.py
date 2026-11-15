"""Logging: one format for the whole platform.

Console: `17:20:01.123  INFO  pipeline     stage start CR-001 run_ab12cd redevelop` (colour when a TTY).
LOG_FORMAT=json switches to one JSON object per line (for log shippers). Everything is also written to
var/logs/mrf.log (rotating, 5 × 5 MB). Agent steps, HTTP requests, gates and LLM calls all log here.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import time

from app.core.config import settings

COLORS = {"DEBUG": "\033[38;5;244m", "INFO": "\033[38;5;39m", "WARNING": "\033[38;5;214m", "ERROR": "\033[38;5;196m",
          "CRITICAL": "\033[1;38;5;196m"}
RESET = "\033[0m"


class PrettyFormatter(logging.Formatter):
    def __init__(self, color: bool):
        super().__init__()
        self.color = color

    def format(self, r: logging.LogRecord) -> str:
        ts = time.strftime("%H:%M:%S", time.localtime(r.created)) + f".{int(r.msecs):03d}"
        name = r.name.removeprefix("mrf.")[:12]
        lvl = {"WARNING": "WARN", "CRITICAL": "CRIT"}.get(r.levelname, r.levelname)
        msg = r.getMessage()
        if r.exc_info:
            msg += "\n" + self.formatException(r.exc_info)
        if self.color:
            return f"\033[38;5;244m{ts}{RESET}  {COLORS.get(lvl, '')}{lvl:<5}{RESET}  \033[38;5;141m{name:<12}{RESET} {msg}"
        return f"{ts}  {lvl:<5}  {name:<12} {msg}"


class JsonFormatter(logging.Formatter):
    def format(self, r: logging.LogRecord) -> str:
        d = {"ts": round(r.created, 3), "level": r.levelname, "logger": r.name, "msg": r.getMessage()}
        for k in ("run_id", "model_id", "agent", "stage", "kind", "tool", "ms", "path", "status"):
            if hasattr(r, k):
                d[k] = getattr(r, k)
        if r.exc_info:
            d["exc"] = self.formatException(r.exc_info)
        return json.dumps(d, default=str)


_done = False


def setup() -> None:
    global _done
    if _done:
        return
    _done = True
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    as_json = os.getenv("LOG_FORMAT", "pretty") == "json"
    root = logging.getLogger("mrf")
    root.setLevel(level)
    root.propagate = False
    con = logging.StreamHandler(sys.stderr)
    con.setFormatter(JsonFormatter() if as_json else PrettyFormatter(sys.stderr.isatty()))
    root.addHandler(con)
    (settings.var_dir / "logs").mkdir(parents=True, exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(settings.var_dir / "logs" / "mrf.log", maxBytes=5_000_000, backupCount=5)
    fh.setFormatter(JsonFormatter() if as_json else PrettyFormatter(False))
    root.addHandler(fh)
    for noisy in ("uvicorn.access",):  # replaced by our request log
        logging.getLogger(noisy).disabled = True


def get(name: str) -> logging.Logger:
    return logging.getLogger(f"mrf.{name}")
