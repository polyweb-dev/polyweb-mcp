"""Unit and integration tests for static SPA serving and HTML5 client-side routing fallback."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from freesearch.api import create_app
from freesearch.config import get_settings


def test_spa_serving_and_html5_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Setup dummy static build
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    assets_dir = static_dir / "assets"
    assets_dir.mkdir()

    index_html = static_dir / "index.html"
    index_html.write_text("<!DOCTYPE html><html><body>FreeSearch React SPA Root</body></html>")

    asset_js = assets_dir / "app.js"
    asset_js.write_text("console.log('freesearch asset');")

    favicon = static_dir / "favicon.ico"
    favicon.write_text("fake-icon")

    monkeypatch.setenv("FREESEARCH_STATIC_DIR", str(static_dir))
    get_settings.cache_clear()

    try:
        app = create_app([])
        with TestClient(app) as client:
            # 1. Root / serves index.html
            root_resp = client.get("/")
            assert root_resp.status_code == 200
            assert "FreeSearch React SPA Root" in root_resp.text
            assert "text/html" in root_resp.headers.get("content-type", "")

            # 2. Client-side routes (/settings, /playground, /usage) fall back to index.html
            settings_resp = client.get("/settings")
            assert settings_resp.status_code == 200
            assert "FreeSearch React SPA Root" in settings_resp.text

            playground_resp = client.get("/playground")
            assert playground_resp.status_code == 200
            assert "FreeSearch React SPA Root" in playground_resp.text

            usage_resp = client.get("/usage")
            assert usage_resp.status_code == 200
            assert "FreeSearch React SPA Root" in usage_resp.text

            # 3. Direct files in static dir are served directly
            fav_resp = client.get("/favicon.ico")
            assert fav_resp.status_code == 200
            assert fav_resp.text == "fake-icon"

            # 4. Mounted /assets files are served directly
            asset_resp = client.get("/assets/app.js")
            assert asset_resp.status_code == 200
            assert "freesearch asset" in asset_resp.text

            # 5. API routes are NOT shadowed by SPA fallback
            api_resp = client.get("/api/v1/providers")
            assert api_resp.status_code == 200
            assert isinstance(api_resp.json(), list)
            assert "FreeSearch React SPA Root" not in api_resp.text

            stats_resp = client.get("/stats")
            assert stats_resp.status_code == 200
            assert "FreeSearch React SPA Root" not in stats_resp.text
    finally:
        get_settings.cache_clear()


def test_spa_disabled_when_static_dir_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FREESEARCH_STATIC_DIR", raising=False)
    get_settings.cache_clear()

    try:
        app = create_app([])
        with TestClient(app) as client:
            resp = client.get("/unknown-route")
            assert resp.status_code == 404
    finally:
        get_settings.cache_clear()
