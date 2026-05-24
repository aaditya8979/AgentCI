"""
Tests for the GitHub webhook handler.

Validates HMAC-SHA256 signature verification, PR event filtering,
and trigger pattern matching.
"""
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from agentci.api.main import app
from agentci.api.webhook import verify_signature, _matches_trigger_patterns


@pytest.fixture
def client():
    return TestClient(app)


WEBHOOK_SECRET = "test-secret-key-12345"


def _sign_payload(payload: bytes, secret: str) -> str:
    """Generate HMAC-SHA256 signature for a payload."""
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def _make_pr_payload(action: str = "opened", repo: str = "owner/repo", pr_number: int = 42) -> dict:
    """Create a minimal PR webhook payload."""
    return {
        "action": action,
        "number": pr_number,
        "repository": {"full_name": repo},
        "pull_request": {
            "title": "Test PR",
            "head": {"sha": "abc123def456"},
            "base": {"sha": "000111222333"},
        },
    }


class TestSignatureVerification:
    """Tests for HMAC-SHA256 signature verification."""

    def test_valid_signature(self):
        payload = b'{"test": true}'
        sig = _sign_payload(payload, "secret")
        assert verify_signature(payload, sig, "secret") is True

    def test_invalid_signature(self):
        payload = b'{"test": true}'
        assert verify_signature(payload, "sha256=invalid", "secret") is False

    def test_wrong_secret(self):
        payload = b'{"test": true}'
        sig = _sign_payload(payload, "correct-secret")
        assert verify_signature(payload, sig, "wrong-secret") is False

    def test_missing_prefix(self):
        assert verify_signature(b"data", "noprefixhash", "secret") is False

    def test_tampered_payload(self):
        original = b'{"amount": 100}'
        tampered = b'{"amount": 999}'
        sig = _sign_payload(original, "secret")
        assert verify_signature(tampered, sig, "secret") is False


class TestTriggerPatterns:
    """Tests for trigger pattern matching."""

    def test_python_files_match(self):
        assert _matches_trigger_patterns(
            ["src/agent.py", "tests/test_agent.py"],
            ["**/*.py"],
        ) is True

    def test_no_match(self):
        assert _matches_trigger_patterns(
            ["README.md", "docs/guide.txt"],
            ["**/*.py"],
        ) is False

    def test_empty_files(self):
        assert _matches_trigger_patterns([], ["**/*.py"]) is False

    def test_multiple_patterns(self):
        assert _matches_trigger_patterns(
            ["deploy/config.yml"],
            ["**/*.py", "**/*.yml"],
        ) is True


class TestWebhookEndpoint:
    """Tests for the /webhook/github endpoint."""

    def test_missing_signature_returns_403(self, client, monkeypatch):
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
        resp = client.post("/webhook/github", json={"test": True})
        assert resp.status_code == 403

    def test_invalid_signature_returns_403(self, client, monkeypatch):
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
        payload = json.dumps({"test": True}).encode()
        resp = client.post(
            "/webhook/github",
            content=payload,
            headers={
                "X-Hub-Signature-256": "sha256=invalid",
                "X-GitHub-Event": "pull_request",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 403

    def test_valid_pr_event_queues_run(self, client, monkeypatch):
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
        pr_payload = _make_pr_payload("opened")
        body = json.dumps(pr_payload).encode()
        sig = _sign_payload(body, WEBHOOK_SECRET)

        resp = client.post(
            "/webhook/github",
            content=body,
            headers={
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "pull_request",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "queued"
        assert data["run_id"] is not None

    def test_ping_event_returns_pong(self, client, monkeypatch):
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
        body = json.dumps({"zen": "test"}).encode()
        sig = _sign_payload(body, WEBHOOK_SECRET)

        resp = client.post(
            "/webhook/github",
            content=body,
            headers={
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "ping",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["action"] == "pong"

    def test_unsupported_pr_action_ignored(self, client, monkeypatch):
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
        pr_payload = _make_pr_payload("closed")
        body = json.dumps(pr_payload).encode()
        sig = _sign_payload(body, WEBHOOK_SECRET)

        resp = client.post(
            "/webhook/github",
            content=body,
            headers={
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "pull_request",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["action"] == "ignored"


class TestHealthEndpoint:
    def test_health_check(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
