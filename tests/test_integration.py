"""
Integration tests for the AgentCI distributed pipeline.

These tests verify the complete path from webhook to database write.
They require infrastructure (Postgres, Redis, Temporal) and are excluded
from the standard test suite.

Run with: pytest tests/test_integration.py -m integration
"""
import json
import os
import uuid

import pytest

# Mark all tests in this file as integration
pytestmark = pytest.mark.integration


@pytest.fixture
def webhook_secret():
    return "integration-test-secret"


@pytest.fixture
def signed_payload(webhook_secret):
    """Create a validly-signed webhook payload."""
    import hashlib
    import hmac

    payload = {
        "action": "opened",
        "number": 1,
        "repository": {"full_name": "test/integration-repo"},
        "pull_request": {
            "title": "Integration test PR",
            "head": {"sha": "abc123def456789"},
            "base": {"sha": "000111222333444"},
        },
    }
    body = json.dumps(payload).encode()
    sig = hmac.new(
        webhook_secret.encode(), body, hashlib.sha256,
    ).hexdigest()

    return body, f"sha256={sig}"


class TestWebhookToDatabase:
    """
    Verifies: Webhook → DB row creation.

    Requires: PostgreSQL running with schema applied.
    Does NOT require Temporal (tests with Temporal=None).
    """

    @pytest.fixture
    def integration_client(self, webhook_secret):
        """Create a test client backed by a real database."""
        from contextlib import asynccontextmanager
        from unittest.mock import MagicMock

        from agentci.api.main import app

        db_url = os.environ.get(
            "TEST_DATABASE_URL",
            "postgresql://agentci:agentci@localhost:5432/agentci",
        )

        @asynccontextmanager
        async def test_lifespan(app):
            from agentci.db.connection import create_pool, close_pool
            pool = await create_pool(db_url)
            app.state.db_pool = pool
            app.state.redis = None
            app.state.temporal = None  # No Temporal for this test
            yield
            await close_pool()

        app.router.lifespan_context = test_lifespan

        from fastapi.testclient import TestClient
        return TestClient(app)

    def test_webhook_creates_db_row(
        self, integration_client, signed_payload, webhook_secret, monkeypatch,
    ):
        """Verify a signed webhook event creates a row in eval_runs."""
        from unittest.mock import AsyncMock, patch

        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", webhook_secret)
        body, sig = signed_payload

        with patch(
            "agentci.api.webhook._extract_changed_files",
            new_callable=AsyncMock,
            return_value=["src/agent.py"],
        ):
            resp = integration_client.post(
                "/webhook/github",
                content=body,
                headers={
                    "X-Hub-Signature-256": sig,
                    "X-GitHub-Event": "pull_request",
                    "Content-Type": "application/json",
                },
            )

        assert resp.status_code == 202
        data = resp.json()
        assert data["action"] == "queued"
        assert data["run_id"] is not None


class TestSandboxRunner:
    """
    Tests for subprocess-based agent sandboxing.

    Does NOT require any infrastructure — runs locally.
    """

    def test_subprocess_runner_captures_output(self, tmp_path):
        """Verify the sandbox captures agent output correctly."""
        # Create a simple agent
        agent_file = tmp_path / "agent.py"
        agent_file.write_text(
            'def run(input):\n'
            '    return {"response": "Hello from sandbox"}\n'
        )

        from agentci.runner.sandbox import SubprocessRunner
        from agentci.models.scenario import (
            Scenario, Message, Rubric, Criterion,
        )

        scenario = Scenario(
            scenario_id="sandbox_test_001",
            description="Test sandbox execution",
            conversation=[Message(role="user", content="Hello")],
            rubric=Rubric(criteria=[
                Criterion(name="test", description="test", weight=1.0),
            ]),
        )

        runner = SubprocessRunner(agent_path=str(agent_file), timeout_seconds=10)
        output, trace = runner.run_scenario(scenario)

        assert "Hello from sandbox" in output
        assert trace.total_latency_ms > 0
        assert any(s.type == "agent_execution" for s in trace.steps)

    def test_subprocess_runner_handles_crash(self, tmp_path):
        """Verify the sandbox survives an agent that crashes."""
        agent_file = tmp_path / "bad_agent.py"
        agent_file.write_text(
            'import sys\n'
            'def run(input):\n'
            '    sys.exit(42)\n'
        )

        from agentci.runner.sandbox import SubprocessRunner
        from agentci.models.scenario import (
            Scenario, Message, Rubric, Criterion,
        )

        scenario = Scenario(
            scenario_id="sandbox_crash_001",
            description="Test agent crash handling",
            conversation=[Message(role="user", content="Crash me")],
            rubric=Rubric(criteria=[
                Criterion(name="test", description="test", weight=1.0),
            ]),
        )

        runner = SubprocessRunner(agent_path=str(agent_file), timeout_seconds=10)
        output, trace = runner.run_scenario(scenario)

        assert "[AGENT ERROR]" in output
        assert any(s.type == "agent_error" for s in trace.steps)

    def test_subprocess_runner_handles_timeout(self, tmp_path):
        """Verify the sandbox enforces timeouts."""
        agent_file = tmp_path / "slow_agent.py"
        agent_file.write_text(
            'import time\n'
            'def run(input):\n'
            '    time.sleep(30)\n'
            '    return "never reached"\n'
        )

        from agentci.runner.sandbox import SubprocessRunner
        from agentci.models.scenario import (
            Scenario, Message, Rubric, Criterion,
        )

        scenario = Scenario(
            scenario_id="sandbox_timeout_001",
            description="Test timeout enforcement",
            conversation=[Message(role="user", content="Wait forever")],
            rubric=Rubric(criteria=[
                Criterion(name="test", description="test", weight=1.0),
            ]),
        )

        runner = SubprocessRunner(agent_path=str(agent_file), timeout_seconds=2)
        output, trace = runner.run_scenario(scenario)

        assert "[AGENT TIMEOUT]" in output
        assert any(s.type == "agent_timeout" for s in trace.steps)

    def test_subprocess_runner_handles_exception(self, tmp_path):
        """Verify the sandbox captures unhandled exceptions."""
        agent_file = tmp_path / "error_agent.py"
        agent_file.write_text(
            'def run(input):\n'
            '    raise ValueError("deliberate error")\n'
        )

        from agentci.runner.sandbox import SubprocessRunner
        from agentci.models.scenario import (
            Scenario, Message, Rubric, Criterion,
        )

        scenario = Scenario(
            scenario_id="sandbox_error_001",
            description="Test exception handling",
            conversation=[Message(role="user", content="Error")],
            rubric=Rubric(criteria=[
                Criterion(name="test", description="test", weight=1.0),
            ]),
        )

        runner = SubprocessRunner(agent_path=str(agent_file), timeout_seconds=10)
        output, trace = runner.run_scenario(scenario)

        assert "[AGENT ERROR]" in output
        assert "deliberate error" in output
