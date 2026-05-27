"""
End-to-end integration tests for AgentCI.

These tests exercise the complete evaluation pipeline. They require
infrastructure (Postgres, Redis, Temporal) and are excluded from the
standard test suite.

Run with:
    AGENTCI_INTEGRATION_TESTS=1 pytest tests/integration/test_e2e.py -v

Gate: These tests only run when AGENTCI_INTEGRATION_TESTS=1 is set.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Skip entire file unless explicitly enabled
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AGENTCI_INTEGRATION_TESTS") != "1",
        reason="Set AGENTCI_INTEGRATION_TESTS=1 to run integration tests",
    ),
]

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parent.parent.parent


class TestCLIEvalPipeline:
    """
    Integration Test 1: CLI eval pipeline.

    Runs agentci eval with a deterministic agent and verifies the output.
    """

    def test_passing_agent_passes(self, tmp_path):
        """The passing agent should score above 0.85 on all scenarios."""
        output_file = tmp_path / "results.json"
        result = subprocess.run(
            [
                sys.executable, "-m", "agentci", "eval",
                "--agent", str(FIXTURES / "passing_agent.py"),
                "--scenarios", str(FIXTURES / "e2e_scenarios.json"),
                "--format", "json",
                "--output", str(output_file),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(ROOT),
        )

        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        # Parse JSON output
        assert output_file.exists(), "Output file not created"
        data = json.loads(output_file.read_text())

        assert data.get("overall_passed") is True, f"Expected pass, got: {data}"
        assert data.get("overall_score", 0) >= 0.85, f"Score too low: {data.get('overall_score')}"
        assert len(data.get("scenarios", [])) == 5, f"Expected 5 scenarios, got {len(data.get('scenarios', []))}"

    def test_failing_agent_fails(self, tmp_path):
        """The failing agent should be detected as a failure."""
        output_file = tmp_path / "results.json"
        result = subprocess.run(
            [
                sys.executable, "-m", "agentci", "eval",
                "--agent", str(FIXTURES / "failing_agent.py"),
                "--scenarios", str(FIXTURES / "e2e_scenarios.json"),
                "--format", "json",
                "--output", str(output_file),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(ROOT),
        )

        # The CLI may return 0 or 1 depending on pass/fail handling
        if output_file.exists():
            data = json.loads(output_file.read_text())
            # The failing agent should NOT pass
            assert data.get("overall_passed") is False, f"Failing agent should not pass: {data}"


class TestDashboardAPIContract:
    """
    Integration Test 3: Dashboard API contract.

    Verifies that API responses match the shape expected by the dashboard.
    """

    @pytest.fixture
    def api_base(self):
        return os.environ.get("AGENTCI_API_URL", "http://localhost:8000")

    @pytest.fixture
    def api_key(self):
        keys = os.environ.get("AGENTCI_API_KEYS", "")
        return keys.split(",")[0].strip() if keys else ""

    def test_runs_endpoint_schema(self, api_base, api_key):
        """GET /api/runs returns correctly shaped data."""
        import httpx

        headers = {"X-API-Key": api_key} if api_key else {}
        resp = httpx.get(f"{api_base}/api/runs", headers=headers)
        assert resp.status_code == 200

        data = resp.json()
        assert "runs" in data
        assert isinstance(data["runs"], list)

        if data["runs"]:
            run = data["runs"][0]
            for field in ["id", "repo", "score", "status"]:
                assert field in run, f"Missing field '{field}' in run response"

    def test_stats_endpoint_schema(self, api_base, api_key):
        """GET /api/stats returns correctly shaped data."""
        import httpx

        headers = {"X-API-Key": api_key} if api_key else {}
        resp = httpx.get(f"{api_base}/api/stats", headers=headers)
        assert resp.status_code == 200

        data = resp.json()
        for field in ["total_runs", "pass_rate"]:
            assert field in data, f"Missing field '{field}' in stats response"

    def test_trends_endpoint_schema(self, api_base, api_key):
        """GET /api/trends returns correctly shaped data."""
        import httpx

        headers = {"X-API-Key": api_key} if api_key else {}
        resp = httpx.get(f"{api_base}/api/trends", headers=headers)
        assert resp.status_code == 200

        data = resp.json()
        assert "trends" in data
        assert isinstance(data["trends"], list)

    def test_health_no_auth_required(self, api_base):
        """GET /health should work without API key."""
        import httpx

        resp = httpx.get(f"{api_base}/health")
        assert resp.status_code in (200, 503)  # 503 if DB not connected
        data = resp.json()
        assert "status" in data

    def test_runs_detail_returns_scenarios(self, api_base, api_key):
        """GET /api/runs/{id} returns scenarios array."""
        import httpx

        headers = {"X-API-Key": api_key} if api_key else {}

        # First get a run ID
        runs_resp = httpx.get(f"{api_base}/api/runs?limit=1", headers=headers)
        if runs_resp.status_code != 200:
            pytest.skip("No API available")

        runs = runs_resp.json().get("runs", [])
        if not runs:
            pytest.skip("No runs in database")

        run_id = runs[0]["id"]
        detail_resp = httpx.get(f"{api_base}/api/runs/{run_id}", headers=headers)
        assert detail_resp.status_code == 200

        data = detail_resp.json()
        assert "scenarios" in data
        assert isinstance(data["scenarios"], list)
