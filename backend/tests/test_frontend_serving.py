from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.frontend import mount_frontend
from app.routers import analysis


@pytest.fixture
def dist(tmp_path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<div id='root'></div>")
    (tmp_path / "assets" / "app.js").write_text("console.log('app')")
    (tmp_path / "favicon.ico").write_bytes(b"icon")
    (tmp_path.parent / "secret.txt").write_text("outside dist")
    return tmp_path


@pytest.fixture
def served(dist) -> TestClient:
    app = FastAPI()
    app.include_router(analysis.router)
    assert mount_frontend(app, dist)
    return TestClient(app)


def test_root_serves_the_app(served):
    res = served.get("/")
    assert res.status_code == 200
    assert "id='root'" in res.text


def test_client_side_routes_fall_back_to_the_app(served):
    assert "id='root'" in served.get("/reports/some/deep/link").text


def test_built_assets_and_top_level_files_are_served(served):
    assert served.get("/assets/app.js").text == "console.log('app')"
    assert served.get("/favicon.ico").content == b"icon"


def test_the_api_still_answers_under_api(served):
    assert served.get("/api/health").json()["status"] == "ok"


def test_unknown_api_paths_are_404_not_the_app(served):
    res = served.get("/api/does-not-exist")
    assert res.status_code == 404
    assert "id='root'" not in res.text


@pytest.mark.parametrize("path", ["/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"])
def test_files_outside_dist_are_never_served(served, path):
    assert "outside dist" not in served.get(path).text


def test_nothing_is_mounted_without_a_build(tmp_path):
    app = FastAPI()
    assert mount_frontend(app, tmp_path / "missing") is False
    assert TestClient(app).get("/").status_code == 404
