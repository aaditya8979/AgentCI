"""
Tests for the statistical significance engine.

Validates Welch's t-test regression detection and Cohen's d effect size
classification against known distributions.
"""
from agentci.stats.significance import is_regression, cohens_d, Severity


class TestCohensD:
    """Tests for Cohen's d effect size computation."""

    def test_identical_distributions(self):
        """Identical samples should produce d ≈ 0."""
        a = [0.90, 0.91, 0.89, 0.90, 0.91]
        b = [0.90, 0.91, 0.89, 0.90, 0.91]
        d = cohens_d(a, b)
        assert abs(d) < 0.01

    def test_large_effect(self):
        """Clearly separated distributions should produce large d."""
        baseline = [0.95, 0.94, 0.96, 0.95, 0.93]
        current = [0.50, 0.52, 0.48, 0.51, 0.49]
        d = cohens_d(baseline, current)
        assert d > 0.8  # Large effect

    def test_positive_direction(self):
        """d should be positive when baseline > current (regression)."""
        baseline = [0.90, 0.91, 0.89]
        current = [0.80, 0.81, 0.79]
        d = cohens_d(baseline, current)
        assert d > 0

    def test_negative_direction(self):
        """d should be negative when current > baseline (improvement)."""
        baseline = [0.80, 0.81, 0.79]
        current = [0.90, 0.91, 0.89]
        d = cohens_d(baseline, current)
        assert d < 0

    def test_single_sample_returns_zero(self):
        """With < 2 samples, d should be 0 (cannot compute)."""
        assert cohens_d([0.9], [0.8]) == 0.0


class TestIsRegression:
    """Tests for the Welch's t-test regression detector."""

    def test_clear_regression_detected(self):
        """A large, consistent score drop should be detected as a regression."""
        baseline = [0.92, 0.89, 0.91, 0.90, 0.93]
        current = [0.75, 0.72, 0.74, 0.73, 0.76]
        result = is_regression(baseline, current)
        assert result.is_regression is True
        assert result.p_value < 0.05
        assert result.severity in (Severity.LARGE, Severity.MEDIUM)

    def test_no_regression_when_stable(self):
        """Minor fluctuations within normal noise should NOT be detected."""
        baseline = [0.90, 0.89, 0.91, 0.90, 0.88]
        current = [0.89, 0.90, 0.88, 0.91, 0.89]
        result = is_regression(baseline, current)
        assert result.is_regression is False

    def test_improvement_not_flagged(self):
        """Scores going UP should never be flagged as a regression."""
        baseline = [0.80, 0.79, 0.81, 0.80, 0.82]
        current = [0.92, 0.93, 0.91, 0.92, 0.94]
        result = is_regression(baseline, current)
        assert result.is_regression is False

    def test_high_variance_not_flagged(self):
        """Same mean delta but high variance → not significant (Blueprint §4.4.3)."""
        baseline = [0.90, 0.70, 0.95, 0.75, 0.85]  # std ≈ 0.10
        current = [0.87, 0.67, 0.92, 0.72, 0.82]   # same noise, shifted -0.03
        result = is_regression(baseline, current)
        # With this much variance, a 0.03 shift should NOT be significant
        assert result.is_regression is False

    def test_result_contains_full_metadata(self):
        """RegressionResult should have all fields populated."""
        baseline = [0.90, 0.91, 0.89]
        current = [0.85, 0.84, 0.86]
        result = is_regression(baseline, current)
        assert result.baseline_mean > 0
        assert result.current_mean > 0
        assert result.baseline_std >= 0
        assert result.current_std >= 0
        assert result.delta != 0
        assert 0.0 <= result.p_value <= 1.0
        assert isinstance(result.severity, Severity)

    def test_summary_string(self):
        """The summary property should produce a readable string."""
        baseline = [0.90, 0.91, 0.89, 0.90, 0.91]
        current = [0.75, 0.72, 0.74, 0.73, 0.76]
        result = is_regression(baseline, current)
        summary = result.summary
        assert "REGRESSION" in summary or "OK" in summary
        assert "Δ=" in summary
        assert "p=" in summary


class TestSeverityClassification:
    """Tests for Cohen's d → Severity mapping."""

    def test_negligible(self):
        """d < 0.2 → NEGLIGIBLE."""
        # Need enough noise that a tiny mean shift produces d < 0.2
        baseline = [0.90, 0.80, 0.95, 0.85, 0.92, 0.88, 0.91, 0.83]
        current = [0.89, 0.81, 0.93, 0.84, 0.91, 0.87, 0.90, 0.84]
        result = is_regression(baseline, current)
        assert result.severity == Severity.NEGLIGIBLE

    def test_large_severity(self):
        """Very separated distributions → LARGE."""
        baseline = [0.95, 0.94, 0.96, 0.95, 0.93]
        current = [0.50, 0.52, 0.48, 0.51, 0.49]
        result = is_regression(baseline, current)
        assert result.severity == Severity.LARGE
