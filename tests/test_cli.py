"""
Tests for the Phase 2 CLI: validate, dry-run, --format json, baseline commands.
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from agentci.cli import main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def valid_scenarios(tmp_path):
    """Create valid scenario files."""
    data = [{
        "scenario_id": "test_001",
        "description": "Test scenario",
        "category": "test",
        "difficulty": "easy",
        "conversation": [{"role": "user", "content": "Hello"}],
        "rubric": {
            "criteria": [
                {"name": "quality", "description": "Good quality", "weight": 0.6},
                {"name": "tone", "description": "Good tone", "weight": 0.4},
            ],
            "passing_threshold": 0.8,
        },
        "context": {},
    }]
    f = tmp_path / "scenarios.json"
    f.write_text(json.dumps(data))
    return f


@pytest.fixture
def invalid_scenarios(tmp_path):
    """Scenarios with bad weights (don't sum to 1.0)."""
    data = [
        {
            "scenario_id": "bad_weights",
            "description": "Bad weight scenario",
            "category": "test",
            "difficulty": "easy",
            "conversation": [{"role": "user", "content": "Hi"}],
            "rubric": {
                "criteria": [
                    {"name": "a", "description": "A", "weight": 0.3},
                    {"name": "b", "description": "B", "weight": 0.3},
                ],
                "passing_threshold": 0.8,
            },
            "context": {},
        },
        {
            "scenario_id": "bad_weights",  # duplicate ID
            "description": "Duplicate",
            "category": "test",
            "difficulty": "easy",
            "conversation": [{"role": "user", "content": "Hi"}],
            "rubric": {
                "criteria": [
                    {"name": "c", "description": "C", "weight": 0.5},
                    {"name": "d", "description": "D", "weight": 0.5},
                ],
                "passing_threshold": 0.8,
            },
            "context": {},
        },
    ]
    f = tmp_path / "bad_scenarios.json"
    f.write_text(json.dumps(data))
    return f


@pytest.fixture
def test_agent(tmp_path):
    """Create a simple test agent."""
    agent = tmp_path / "agent.py"
    agent.write_text(
        'def run(input_data):\n'
        '    msgs = input_data.get("messages", [])\n'
        '    return f"Response to: {msgs[-1][\'content\'] if msgs else \'nothing\'}"\n'
    )
    return agent


class TestValidateCommand:
    """Tests for agentci validate."""

    def test_valid_scenarios_pass(self, runner, valid_scenarios):
        result = runner.invoke(main, ["validate", str(valid_scenarios)])
        assert result.exit_code == 0
        assert "PASS" in result.output
        assert "All valid" in result.output

    def test_invalid_scenarios_fail(self, runner, invalid_scenarios):
        result = runner.invoke(main, ["validate", str(invalid_scenarios)])
        assert result.exit_code == 1
        assert "FAIL" in result.output

    def test_invalid_json_fails(self, runner, tmp_path):
        bad_json = tmp_path / "bad.json"
        bad_json.write_text("{not valid json")
        result = runner.invoke(main, ["validate", str(bad_json)])
        assert result.exit_code == 1

    def test_nonexistent_file_fails(self, runner):
        result = runner.invoke(main, ["validate", "/nonexistent/file.json"])
        assert result.exit_code != 0


class TestDryRun:
    """Tests for agentci eval --dry-run."""

    def test_dry_run_skips_judges(self, runner, valid_scenarios, test_agent):
        result = runner.invoke(main, [
            "eval", "-a", str(test_agent), "-s", str(valid_scenarios), "--dry-run"
        ])
        assert result.exit_code == 0
        assert "Dry run complete" in result.output or "dry_run" in result.output
        assert "No scoring performed" in result.output or "scenarios_executed" in result.output

    def test_dry_run_json_format(self, runner, valid_scenarios, test_agent):
        result = runner.invoke(main, [
            "eval", "-a", str(test_agent), "-s", str(valid_scenarios),
            "--dry-run", "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["mode"] == "dry_run"
        assert data["scenarios_executed"] == 1


class TestJsonFormat:
    """Tests for agentci eval --format json (non-dry-run requires API keys, so we test structure)."""

    def test_dry_run_json_has_correct_keys(self, runner, valid_scenarios, test_agent):
        result = runner.invoke(main, [
            "eval", "-a", str(test_agent), "-s", str(valid_scenarios),
            "--dry-run", "--format", "json",
        ])
        data = json.loads(result.output)
        assert "mode" in data
        assert "scenarios_executed" in data
        assert "duration_seconds" in data


class TestBaselineCommands:
    """Tests for agentci baseline list/show/clear."""

    def test_baseline_list_empty(self, runner, tmp_path):
        result = runner.invoke(main, ["baseline", "list", "--dir", str(tmp_path / "empty")])
        assert result.exit_code == 0
        assert "No baselines" in result.output

    def test_baseline_list_with_data(self, runner, tmp_path):
        from agentci.stats.baseline import BaselineStore
        store = BaselineStore(tmp_path / "baselines")
        store.append_score("scenario_a", 0.92)
        store.append_score("scenario_a", 0.88)

        result = runner.invoke(main, ["baseline", "list", "--dir", str(tmp_path / "baselines")])
        assert result.exit_code == 0
        assert "scenario_a" in result.output

    def test_baseline_show(self, runner, tmp_path):
        from agentci.stats.baseline import BaselineStore
        store = BaselineStore(tmp_path / "baselines")
        store.append_score("test_s", 0.91)

        result = runner.invoke(main, [
            "baseline", "show", "test_s", "--dir", str(tmp_path / "baselines"),
        ])
        assert result.exit_code == 0
        assert "0.910" in result.output

    def test_baseline_show_empty(self, runner, tmp_path):
        result = runner.invoke(main, [
            "baseline", "show", "nonexistent", "--dir", str(tmp_path / "missing"),
        ])
        assert result.exit_code == 0
        assert "No baseline data" in result.output

    def test_baseline_clear(self, runner, tmp_path):
        from agentci.stats.baseline import BaselineStore
        store = BaselineStore(tmp_path / "baselines")
        store.append_score("clearme", 0.50)

        result = runner.invoke(main, [
            "baseline", "clear", "--dir", str(tmp_path / "baselines"), "--yes",
        ])
        assert result.exit_code == 0
        assert "Cleared" in result.output


class TestInitCommand:
    """Tests for agentci init."""

    def test_init_creates_files(self, runner, tmp_path):
        project = tmp_path / "new_project"
        project.mkdir()
        result = runner.invoke(
            main,
            ["init", "--path", str(project)],
            input="A test agent\nother\nopenai\n",
        )
        assert result.exit_code == 0
        assert (project / ".agentci.yml").exists()
        assert (project / ".agentci" / "scenarios.json").exists()
        assert (project / "eval" / "example_agent.py").exists()


class TestVersionCommand:
    """Test version output."""

    def test_version(self, runner):
        result = runner.invoke(main, ["--version"])
        assert "0.2.0" in result.output
