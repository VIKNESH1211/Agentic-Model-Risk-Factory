import os
import tempfile

os.environ["MRF_VAR_DIR"] = tempfile.mkdtemp(prefix="mrf_test_")
os.environ["DEMO_PACE"] = "0"
os.environ["LLM_PROVIDER"] = "offline"
for k in ("OPENAI_API_KEY", "GROQ_API_KEY", "LLM_API_KEY", "ANTHROPIC_API_KEY"):
    os.environ[k] = ""  # tests never call a real provider

import pytest  # noqa: E402

from app.core.db import drop_all, init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    drop_all()
    init_db()
    from app.services import policy, prompts
    prompts._cache.clear()
    prompts.seed()
    policy.seed()
    yield
