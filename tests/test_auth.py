"""
Tests for API authentication middleware.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api_keys():
    return "test-key-1,test-key-2"


@pytest.fixture
def app_with_auth(api_keys):
    """Create a FastAPI app with auth middleware for testing."""
    from fastapi import FastAPI, Request

    app = FastAPI()

    @app.middleware("http")
    async def api_key_middleware(request: Request, call_next):
        path = request.url.path
        # Exempt paths
        if path in ("/health", "/webhook/github") or path.startswith("/webhook/"):
            return await call_next(request)
        if path.startswith("/api/"):
            api_key = request.headers.get("X-API-Key", "")
            valid_keys = [k.strip() for k in api_keys.split(",") if k.strip()]
            if api_key not in valid_keys:
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=401,
                    content={"error": "unauthorized", "message": "Valid API key required in X-API-Key header."},
                )
        return await call_next(request)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/runs")
    async def list_runs():
        return {"runs": []}

    return app


class TestAPIKeyMiddleware:

    def test_missing_key_returns_401(self, app_with_auth):
        client = TestClient(app_with_auth)
        resp = client.get("/api/runs")
        assert resp.status_code == 401
        assert resp.json()["error"] == "unauthorized"

    def test_invalid_key_returns_401(self, app_with_auth):
        client = TestClient(app_with_auth)
        resp = client.get("/api/runs", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 401

    def test_valid_key_returns_200(self, app_with_auth):
        client = TestClient(app_with_auth)
        resp = client.get("/api/runs", headers={"X-API-Key": "test-key-1"})
        assert resp.status_code == 200

    def test_second_valid_key_returns_200(self, app_with_auth):
        client = TestClient(app_with_auth)
        resp = client.get("/api/runs", headers={"X-API-Key": "test-key-2"})
        assert resp.status_code == 200

    def test_health_exempt(self, app_with_auth):
        client = TestClient(app_with_auth)
        resp = client.get("/health")
        assert resp.status_code == 200
