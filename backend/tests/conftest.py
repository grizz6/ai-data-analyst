import os
from pathlib import Path

# Tests must never write to the real database file. This has to be set before
# app.config is imported, because the store opens its file at import time.
os.environ["ADA_DATABASE_PATH"] = ":memory:"
# Same idea for the built frontend: tests behave the same whether or not
# frontend/dist exists on this machine.
os.environ["ADA_FRONTEND_DIST"] = str(Path(__file__).parent / "no-frontend-build")

import pytest
from fastapi.testclient import TestClient

from app import rate_limit
from app.config import settings
from app.main import app

SAMPLE_CSV = Path(__file__).resolve().parents[2] / "sample-data" / "sales_sample.csv"


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    """Tests never reach a real provider, even when backend/.env holds a key.

    Tests that exercise the model layer opt back in with a fake key and a fake transport.
    """
    monkeypatch.setattr(settings, "llm_api_key", "")


@pytest.fixture(autouse=True)
def fresh_rate_limits():
    """Each test starts with no requests counted against the per-hour limits."""
    limiters = (rate_limit.uploads, rate_limit.plans)
    for limiter in limiters:
        limiter.reset()
    yield
    for limiter in limiters:
        limiter.reset()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def sample_csv_bytes() -> bytes:
    return SAMPLE_CSV.read_bytes()


@pytest.fixture
def result_for_store():
    from app.services.pipeline import compute_analysis

    return compute_analysis(SAMPLE_CSV.read_bytes(), "sales_sample.csv")
