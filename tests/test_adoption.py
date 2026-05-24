"""Tests for the adoption layer modules."""
import json
import os
import tempfile
from pathlib import Path

import pytest

# ── Framework Detector ───────────────────────────────────────────────────────

from agentci.enterprise.framework_detector import detect_framework, DetectionResult


class TestFrameworkDetector:
    def test_detects_langchain(self, tmp_path):
        (tmp_path / "agent.py").write_text("from langchain.agents import AgentExecutor\n")
        result = detect_framework(tmp_path)
        assert result.primary_framework == "langchain"
        assert result.detected

    def test_detects_openai(self, tmp_path):
        (tmp_path / "bot.py").write_text("import openai\nclient = openai.Client()\n")
        result = detect_framework(tmp_path)
        assert result.primary_framework == "openai"
        assert "bot.py" in result.agent_candidates[0]

    def test_no_framework(self, tmp_path):
        (tmp_path / "utils.py").write_text("import os\nprint('hello')\n")
        result = detect_framework(tmp_path)
        assert result.primary_framework == "unknown"
        assert not result.detected

    def test_skips_venv(self, tmp_path):
        venv = tmp_path / "venv" / "lib"
        venv.mkdir(parents=True)
        (venv / "langchain_stuff.py").write_text("from langchain import x\n")
        result = detect_framework(tmp_path)
        assert result.primary_framework == "unknown"

    def test_detects_entry_point(self, tmp_path):
        (tmp_path / "my_agent.py").write_text('import openai\ndef run():\n    pass\n')
        result = detect_framework(tmp_path)
        assert "my_agent.py" in result.recommended_entry


# ── Scenario Generation ──────────────────────────────────────────────────────

from agentci.enterprise.scenario_gen import (
    extract_constraints, generate_from_system_prompt,
    generate_from_logs, anonymize_pii, write_scenarios,
)


class TestConstraintExtraction:
    def test_extracts_forbidden(self):
        prompt = "You must never recommend specific stocks.\nAlways be polite."
        constraints = extract_constraints(prompt)
        assert any(c.type == "forbidden" for c in constraints)

    def test_extracts_required(self):
        prompt = "You must always verify the user's identity before proceeding."
        constraints = extract_constraints(prompt)
        assert any(c.type == "required" for c in constraints)

    def test_extracts_policy(self):
        prompt = "Our refund policy allows returns within 30-day window."
        constraints = extract_constraints(prompt)
        assert any(c.type == "policy" for c in constraints)

    def test_empty_prompt(self):
        assert extract_constraints("") == []


class TestScenarioGeneration:
    def test_generates_from_prompt(self):
        prompt = "You are a support agent.\nNever recommend competitors.\nAlways escalate billing disputes."
        scenarios = generate_from_system_prompt(prompt, count=10)
        assert len(scenarios) > 0
        assert all(s.scenario_id for s in scenarios)

    def test_count_limit(self):
        prompt = "Never do X.\nNever do Y.\nAlways do Z.\nPolicy: 30-day return.\n" * 5
        scenarios = generate_from_system_prompt(prompt, count=5)
        assert len(scenarios) <= 5

    def test_generates_from_logs(self, tmp_path):
        logs = tmp_path / "logs.jsonl"
        entries = [
            {"conversation": [{"role": "user", "content": "I'm frustrated!"}, {"role": "assistant", "content": "Sorry."}]},
            {"conversation": [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi!"}]},
        ]
        logs.write_text("\n".join(json.dumps(e) for e in entries))
        scenarios = generate_from_logs(logs, count=5)
        # At least the frustrated conversation should be interesting
        assert len(scenarios) >= 1

    def test_write_scenarios(self, tmp_path):
        prompt = "Never recommend stocks. Always be polite."
        scenarios = generate_from_system_prompt(prompt, count=5)
        output = tmp_path / "out.json"
        write_scenarios(scenarios, output)
        assert output.exists()
        data = json.loads(output.read_text())
        assert isinstance(data, list)


class TestPIIAnonymization:
    def test_redacts_email(self):
        assert "[REDACTED_EMAIL]" in anonymize_pii("Contact john@example.com")

    def test_redacts_phone(self):
        assert "[REDACTED_PHONE]" in anonymize_pii("Call 555-123-4567")

    def test_redacts_ssn(self):
        assert "[REDACTED_SSN]" in anonymize_pii("SSN: 123-45-6789")

    def test_redacts_cc(self):
        assert "[REDACTED_CC]" in anonymize_pii("Card: 4111-1111-1111-1111")

    def test_preserves_normal_text(self):
        text = "Hello, how are you today?"
        assert anonymize_pii(text) == text


# ── Keys ─────────────────────────────────────────────────────────────────────

from agentci.enterprise.keys import resolve_key, check_all_keys, _load_dotenv


class TestKeys:
    def test_resolve_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test123")
        key, source = resolve_key("openai")
        assert key == "sk-test123"
        assert source == "env"

    def test_resolve_from_dotenv(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        dotenv = tmp_path / ".env"
        dotenv.write_text("OPENAI_API_KEY=sk-fromfile\n")
        key, source = resolve_key("openai", tmp_path)
        assert key == "sk-fromfile"
        assert source == "dotenv"

    def test_resolve_missing(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        key, source = resolve_key("openai", "/nonexistent")
        assert key == ""

    def test_load_dotenv(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("KEY1=value1\n# comment\nKEY2='value2'\n")
        result = _load_dotenv(f)
        assert result["KEY1"] == "value1"
        assert result["KEY2"] == "value2"

    def test_check_all_keys(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        statuses = check_all_keys()
        assert len(statuses) == 3
        openai_status = next(s for s in statuses if s.provider == "openai")
        assert openai_status.found


# ── Diff Sampler ─────────────────────────────────────────────────────────────

from agentci.enterprise.diff_sampler import categorize_file, parse_diff, sample_scenarios, FileCategory


class TestDiffSampler:
    def test_categorize_system_prompt(self):
        assert categorize_file("prompts/system_prompt.txt") == FileCategory.SYSTEM_PROMPT

    def test_categorize_agent_logic(self):
        assert categorize_file("src/agent.py") == FileCategory.AGENT_LOGIC

    def test_categorize_infrastructure(self):
        assert categorize_file("docker/Dockerfile") == FileCategory.INFRASTRUCTURE

    def test_categorize_tool(self):
        assert categorize_file("tools/tool_definitions.py") == FileCategory.TOOL_DEFINITIONS

    def test_sample_returns_minimum(self):
        from agentci.enterprise.diff_sampler import DiffFile
        files = [DiffFile(path="infra/deploy.yml", category=FileCategory.INFRASTRUCTURE)]
        result = sample_scenarios(files, [f"s_{i}" for i in range(20)], min_scenarios=10)
        assert len(result.recommended_scenarios) >= 10


# ── Output Cache ─────────────────────────────────────────────────────────────

from agentci.cache.output_cache import OutputCache


class TestOutputCache:
    def test_cache_miss(self):
        cache = OutputCache()
        assert cache.get("s1", "v1", "output") is None
        assert cache.stats.misses == 1

    def test_cache_hit(self):
        cache = OutputCache()
        cache.put("s1", "v1", "output", {"score": 0.9})
        result = cache.get("s1", "v1", "output")
        assert result == {"score": 0.9}
        assert cache.stats.hits == 1

    def test_cache_different_output(self):
        cache = OutputCache()
        cache.put("s1", "v1", "output_a", {"score": 0.9})
        assert cache.get("s1", "v1", "output_b") is None

    def test_cache_report(self):
        cache = OutputCache()
        cache.put("s1", "v1", "out", {"score": 0.9})
        cache.get("s1", "v1", "out")  # hit
        cache.get("s1", "v1", "out2")  # miss
        assert "50%" in cache.stats.report()


# ── Governance ───────────────────────────────────────────────────────────────

from agentci.enterprise.governance import create_attestation, save_attestation, load_and_verify


class TestGovernance:
    def test_create_attestation(self):
        att = create_attestation(run_id="test-123", repo="acme/agent")
        assert att.run_id == "test-123"
        assert att.signature
        assert att.verify()

    def test_tampered_attestation(self):
        att = create_attestation(run_id="test-123")
        att.overall_score = 0.99  # tamper
        assert not att.verify()

    def test_save_and_load(self, tmp_path):
        att = create_attestation(run_id="test-456", repo="acme/bot")
        path = tmp_path / "att.json"
        save_attestation(att, path)
        loaded, valid = load_and_verify(path)
        assert valid
        assert loaded.run_id == "test-456"


# ── Approval ─────────────────────────────────────────────────────────────────

from agentci.enterprise.approval import (
    evaluate_policy, is_approval_comment, check_approver_authorized,
    ApprovalAction, DEFAULT_POLICIES,
)
from agentci.enterprise.severity import SeverityTier


class TestApproval:
    def test_cosmetic_warns(self):
        policy = evaluate_policy(SeverityTier.COSMETIC)
        assert policy.action == ApprovalAction.WARN

    def test_safety_requires_approval(self):
        policy = evaluate_policy(SeverityTier.SAFETY)
        assert policy.action == ApprovalAction.BLOCK_AND_REQUIRE_APPROVAL

    def test_approval_comment(self):
        assert is_approval_comment("/agentci approve")
        assert is_approval_comment("  /agentci approve  ")
        assert not is_approval_comment("looks good to me")

    def test_approver_authorized(self):
        policy = evaluate_policy(SeverityTier.SAFETY)
        teams = {"security_team": ["alice", "bob"]}
        assert check_approver_authorized("alice", policy, teams)
        assert not check_approver_authorized("eve", policy, teams)


# ── Calibration ──────────────────────────────────────────────────────────────

from agentci.judge.calibration import compute_spearman, compute_calibration, GoldenEntry, CalibrationProfile


class TestCalibration:
    def test_perfect_spearman(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert abs(compute_spearman(x, x) - 1.0) < 0.01

    def test_inverse_spearman(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [5.0, 4.0, 3.0, 2.0, 1.0]
        assert abs(compute_spearman(x, y) - (-1.0)) < 0.01

    def test_compute_calibration(self):
        golden = [
            GoldenEntry(scenario_id="s1", agent_output_hash="h1", human_scores={"accuracy": 0.9, "tone": 0.8}),
            GoldenEntry(scenario_id="s2", agent_output_hash="h2", human_scores={"accuracy": 0.5, "tone": 0.6}),
            GoldenEntry(scenario_id="s3", agent_output_hash="h3", human_scores={"accuracy": 0.7, "tone": 0.7}),
        ]
        judge_scores = {
            "s1": {"accuracy": 0.95, "tone": 0.85},
            "s2": {"accuracy": 0.55, "tone": 0.65},
            "s3": {"accuracy": 0.75, "tone": 0.75},
        }
        metrics = compute_calibration(golden, judge_scores, "gpt-4o")
        assert metrics.sample_size == 6
        assert metrics.spearman_correlation > 0.8  # should be near perfect
        assert metrics.mean_score_delta > 0  # judge is slightly lenient

    def test_calibration_profile_correction(self):
        from agentci.judge.calibration import CalibrationMetrics
        profile = CalibrationProfile(
            models={"gpt-4o": CalibrationMetrics(model="gpt-4o", mean_score_delta=0.05)},
        )
        corrected = profile.correction_for("gpt-4o", 0.9)
        assert abs(corrected - 0.85) < 0.01
