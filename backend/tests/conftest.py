import os
import tempfile

os.environ["MRF_VAR_DIR"] = tempfile.mkdtemp(prefix="mrf_test_")
os.environ["DEMO_PACE"] = "0"
os.environ["LLM_PROVIDER"] = "offline"

import pytest  # noqa: E402

from app.core.db import drop_all, init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    drop_all()
    init_db()
    yield
