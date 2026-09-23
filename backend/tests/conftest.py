import os
from pathlib import Path

# Tests must never write to the real database file. This has to be set before
# app.config is imported, because the store opens its file at import time.
os.environ["ADA_DATABASE_PATH"] = ":memory:"

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

SAMPLE_CSV = Path(__file__).resolve().parents[2] / "sample-data" / "sales_sample.csv"


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    """Tests never reach a real provider, even when backend/.env holds a key.

    Tests that exercise the model layer opt back in with a fake key and a fake transport.
    """
    monkeypatch.setattr(settings, "llm_api_key", "")


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def sample_csv_bytes() -> bytes:
    return SAMPLE_CSV.read_bytes()
