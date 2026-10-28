"""Serve the built reviewer when present, retaining the source-only test page."""

from fastapi.testclient import TestClient
from review_support import setup_review

from survey.review import api


def test_no_build_serves_existing_test_page(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "FRONTEND_DIST", tmp_path / "no-build")
    _, settings = setup_review(tmp_path, with_git=True)
    with TestClient(
        api.create_app(settings, require_prepared=False),
        base_url="http://127.0.0.1:8765",
    ) as client:
        assert "integration test" in client.get("/").text
        assert client.get("/app.js").status_code == 200
        assert client.get("/api/health").json()["ready"]


def test_build_served_outside_cwd_and_api_routes_still_work(tmp_path, monkeypatch):
    dist = tmp_path / "frontend" / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text('<script src="/assets/reviewer.js"></script>')
    (assets / "reviewer.js").write_text("/* built reviewer */")
    (dist.parent / "private.txt").write_text("not a public asset")
    monkeypatch.setattr(api, "FRONTEND_DIST", dist)
    _, settings = setup_review(tmp_path, with_git=True)
    monkeypatch.chdir(tmp_path)
    with TestClient(
        api.create_app(settings, require_prepared=False),
        base_url="http://127.0.0.1:8765",
    ) as client:
        assert client.get("/").text == '<script src="/assets/reviewer.js"></script>'
        response = client.get("/assets/reviewer.js")
        assert response.status_code == 200 and response.text == "/* built reviewer */"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert client.get("/private.txt").status_code == 404
        assert client.get("/%2e%2e/private.txt").status_code == 404
        assert client.get("/api/health").json()["ready"]
        assert client.get("/api/queue?region=demo").json()["items"]
        assert client.get("/docs").status_code == 200
