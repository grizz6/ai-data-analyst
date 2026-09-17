from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

SAMPLE_CSV = Path(__file__).resolve().parents[2] / "sample-data" / "sales_sample.csv"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def sample_csv_bytes() -> bytes:
    return SAMPLE_CSV.read_bytes()
