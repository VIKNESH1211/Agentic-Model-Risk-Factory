"""Runtime settings, read from environment (.env supported)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]  # model-risk-factory/
load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


_MODEL_DEFAULTS = {"openai": ("gpt-4o-mini", "gpt-4o-mini"), "groq": ("openai/gpt-oss-120b", "openai/gpt-oss-20b"),
                   "anthropic": ("claude-sonnet-5-5", "")}
_MODEL_FAMILY = {"openai": ("gpt-", "o1", "o3", "o4", "chatgpt"), "groq": ("openai/", "qwen/", "moonshotai/", "meta-llama/"),
                 "anthropic": ("claude",)}


def _model(env: str, provider: str, idx: int) -> str:
    """Model from env if it belongs to the provider's family (a leftover name from another provider is ignored)."""
    v = os.getenv(env, "")
    fam = _MODEL_FAMILY.get(provider, ())
    return v if v and (not fam or v.startswith(fam)) else _MODEL_DEFAULTS.get(provider, ("", ""))[idx]


class Settings:
    root: Path = ROOT
    legacy_dir: Path = ROOT / "legacy_models"
    data_dir: Path = ROOT / "data"
    var_dir: Path = Path(os.getenv("MRF_VAR_DIR", str(ROOT / "var")))
    llm_cache_dir: Path = ROOT / "demo" / "llm_cache"

    db_url: str = os.getenv("DATABASE_URL", "")
    # Provider follows the key that is present (OPENAI_API_KEY → openai, a gsk_… key → groq), else LLM_PROVIDER.
    _openai_key = os.getenv("OPENAI_API_KEY", "")
    _key_any = os.getenv("GROQ_API_KEY") or os.getenv("LLM_API_KEY", "")
    _is_groq = _key_any.startswith("gsk_")
    llm_provider: str = "openai" if _openai_key else "groq" if _is_groq else os.getenv("LLM_PROVIDER", "offline")
    llm_model: str = _model("LLM_MODEL", llm_provider, 0)
    llm_fast_model: str = _model("LLM_FAST_MODEL", llm_provider, 1)  # cheaper model for agent steps
    openai_api_key: str = _openai_key or (os.getenv("LLM_API_KEY", "") if llm_provider == "openai" else "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    groq_api_key: str = _key_any if _is_groq else ""
    llm_api_key: str = os.getenv("ANTHROPIC_API_KEY") or (os.getenv("LLM_API_KEY", "") if llm_provider == "anthropic" else "")
    llm_mode: str = os.getenv("LLM_MODE", "replay")  # live | record | replay
    max_run_cost: float = float(os.getenv("MAX_RUN_COST", "2.0"))
    max_run_tokens: int = int(os.getenv("MAX_RUN_TOKENS", "200000"))

    sandbox_mode: str = os.getenv("SANDBOX_MODE", "auto")  # auto | docker | reference
    sandbox_image: str = os.getenv("SANDBOX_IMAGE", "mrf-rsandbox:latest")
    sandbox_timeout: int = int(os.getenv("SANDBOX_TIMEOUT", "120"))

    allow_tamper_demo: bool = _bool("ALLOW_TAMPER_DEMO", True)
    demo_pace: float = float(os.getenv("DEMO_PACE", "0.35"))  # seconds between visible steps
    mlflow_uri: str = os.getenv("MLFLOW_TRACKING_URI", "")

    @property
    def database_url(self) -> str:
        return self.db_url or f"sqlite:///{self.var_dir / 'mrf.db'}"

    @property
    def runs_dir(self) -> Path:
        return self.var_dir / "runs"


settings = Settings()
settings.var_dir.mkdir(parents=True, exist_ok=True)
settings.runs_dir.mkdir(parents=True, exist_ok=True)
