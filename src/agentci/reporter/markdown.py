"""
Markdown reporter for generating GitHub PR comments.

Produces the detailed eval report described in the blueprint, formatted
as a GitHub-compatible markdown comment with collapsible failure details.
"""
from __future__ import annotations

from ..models.scenario import ScenarioResult
from ..stats.significance import RegressionResult


class MarkdownReporter:
    """Generates GitHub PR comment markdown from evaluation results."""

    @staticmethod
    def generate_report(
        results: list[ScenarioResult],
        regressions: dict[str, RegressionResult] | None = None,
        commit_sha: str = "unknown",
        suite_name: str = "full",
        duration_seconds: float = 0.0,
    ) -> str:
        """
        Generate a complete markdown evaluation report.

        Args:
            results: List of ScenarioResult objects.
            regressions: Optional mapping of scenario_id → RegressionResult.
            commit_sha: Short commit SHA for the report header.
            suite_name: Name of the eval suite that was run.
            duration_seconds: Total evaluation duration.

        Returns:
            Formatted markdown string ready for GitHub PR comment.
        """
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        failed = total - passed
        avg_score = sum(r.weighted_score for r in results) / total if total else 0.0

        overall_status = "✅ PASSED" if failed == 0 else "❌ FAILED"
        minutes = int(duration_seconds // 60)
        seconds = int(duration_seconds % 60)

        lines: list[str] = []

        # Header
        lines.append("## 🔍 AgentCI Eval Report")
        lines.append("")
        lines.append(
            f"**Commit:** `{commit_sha[:7]}` | "
            f"**Suite:** `{suite_name}` | "
            f"**Duration:** {minutes}m {seconds}s"
        )
        lines.append("")
        lines.append(f"### 📊 Overall: {overall_status} ({avg_score:.2f})")
        lines.append("")

        # Results table
        lines.append("| Scenario | Score | Baseline | Delta | Status |")
        lines.append("|----------|-------|----------|-------|--------|")

        for r in results:
            score_str = f"{r.weighted_score:.2f}"
            baseline_str = "—"
            delta_str = "—"

            if r.passed:
                status = "✅"
            else:
                status = "❌"

            if regressions and r.scenario_id in regressions:
                reg = regressions[r.scenario_id]
                baseline_str = f"{reg.baseline_mean:.2f}"
                delta_str = f"{reg.delta:+.2f}"
                if reg.is_regression:
                    status = f"❌ (p={reg.p_value:.3f})"
                elif not r.passed:
                    status = f"❌"
                else:
                    status = f"✅ (p={reg.p_value:.2f})"

            lines.append(
                f"| {r.scenario_id} | {score_str} | "
                f"{baseline_str} | {delta_str} | {status} |"
            )

        # Failed scenario details
        failed_results = [r for r in results if not r.passed]
        if failed_results:
            lines.append("")
            lines.append("### ❌ Failed Scenarios")
            lines.append("")

            for r in failed_results:
                lines.append(f"<details>")
                lines.append(
                    f"<summary><b>{r.scenario_id}</b> — "
                    f"Score: {r.weighted_score:.2f}</summary>"
                )
                lines.append("")

                # Per-criterion breakdown
                for name, score in r.scores.items():
                    icon = "✅" if score >= 0.8 else "⚠️" if score >= 0.5 else "❌"
                    lines.append(f"- {icon} **{name}**: {score:.2f}")

                if r.judge_reasonings:
                    lines.append("")
                    for judge, reasoning in r.judge_reasonings.items():
                        lines.append(f"**{judge}:** {reasoning[:300]}")
                        lines.append("")

                lines.append("</details>")
                lines.append("")

        # Footer
        lines.append("---")
        lines.append("*Powered by AgentCI v0.1.0*")

        return "\n".join(lines)
