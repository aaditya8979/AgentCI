"""
Rich console reporter for AgentCI evaluation results.

Renders beautiful terminal output using the Rich library with
colour-coded pass/fail status, score deltas, and detailed
failure breakdowns.
"""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..models.scenario import ScenarioResult
from ..stats.significance import RegressionResult, Severity


console = Console()


class ConsoleReporter:
    """Renders evaluation results to the terminal with Rich formatting."""

    @staticmethod
    def print_header(title: str, subtitle: str = "") -> None:
        """Print a branded header panel."""
        header_text = Text()
        header_text.append("⚡ AgentCI", style="bold cyan")
        header_text.append(f"  —  {title}", style="bold white")
        if subtitle:
            header_text.append(f"\n{subtitle}", style="dim white")

        console.print(Panel(
            header_text,
            border_style="cyan",
            padding=(1, 2),
        ))

    @staticmethod
    def print_scenario_table(
        results: list[ScenarioResult],
        regressions: dict[str, RegressionResult] | None = None,
    ) -> None:
        """
        Print a summary table of all scenario results.

        Args:
            results: List of ScenarioResult from the evaluation.
            regressions: Optional mapping of scenario_id → RegressionResult
                         for baseline comparison.
        """
        table = Table(
            title="Scenario Results",
            show_header=True,
            header_style="bold magenta",
            border_style="dim",
            padding=(0, 1),
        )

        table.add_column("Scenario", style="white", min_width=30)
        table.add_column("Score", justify="center", min_width=8)
        table.add_column("Baseline", justify="center", min_width=10)
        table.add_column("Δ", justify="center", min_width=8)
        table.add_column("p-value", justify="center", min_width=10)
        table.add_column("Status", justify="center", min_width=10)

        for r in results:
            score_str = f"{r.weighted_score:.3f}"
            score_style = "green" if r.passed else "red"

            baseline_str = "—"
            delta_str = "—"
            p_str = "—"
            status = Text("✅ PASS", style="bold green") if r.passed else Text("❌ FAIL", style="bold red")

            if regressions and r.scenario_id in regressions:
                reg = regressions[r.scenario_id]
                baseline_str = f"{reg.baseline_mean:.3f}"
                delta_str = f"{reg.delta:+.3f}"
                delta_style = "green" if reg.delta >= 0 else "red"
                delta_str_styled = f"[{delta_style}]{delta_str}[/{delta_style}]"
                p_str = f"{reg.p_value:.4f}"

                if reg.is_regression:
                    severity_colors = {
                        Severity.NEGLIGIBLE: "yellow",
                        Severity.SMALL: "yellow",
                        Severity.MEDIUM: "red",
                        Severity.LARGE: "bold red",
                    }
                    sev_color = severity_colors.get(reg.severity, "red")
                    status = Text(f"❌ {reg.severity.value.upper()}", style=sev_color)
            else:
                delta_str_styled = delta_str

            table.add_row(
                r.scenario_id,
                f"[{score_style}]{score_str}[/{score_style}]",
                baseline_str,
                delta_str_styled,
                p_str,
                status,
            )

        console.print(table)

    @staticmethod
    def print_failure_details(
        result: ScenarioResult,
        regression: RegressionResult | None = None,
    ) -> None:
        """Print detailed breakdown for a failed scenario."""
        detail = Text()
        detail.append(f"Scenario: {result.scenario_id}\n", style="bold white")
        detail.append(f"Weighted Score: {result.weighted_score:.4f}\n", style="red")

        if regression:
            detail.append(f"Baseline Mean:  {regression.baseline_mean:.4f}\n", style="dim")
            detail.append(f"Delta:          {regression.delta:+.4f}\n", style="red")
            detail.append(f"Effect Size:    {regression.effect_size:.3f} ({regression.severity.value})\n", style="dim")
            detail.append(f"p-value:        {regression.p_value:.6f}\n", style="dim")

        detail.append("\nPer-Criterion Scores:\n", style="bold")
        for name, score in result.scores.items():
            bar_len = int(score * 20)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            score_color = "green" if score >= 0.8 else "yellow" if score >= 0.5 else "red"
            detail.append(f"  {name:30s} [{score_color}]{bar} {score:.3f}[/{score_color}]\n")

        if result.judge_reasonings:
            detail.append("\nJudge Reasoning:\n", style="bold")
            for judge_name, reasoning in result.judge_reasonings.items():
                detail.append(f"  [{judge_name}]: {reasoning[:200]}\n", style="dim")

        console.print(Panel(detail, title="Failure Detail", border_style="red"))

    @staticmethod
    def print_summary(
        total: int,
        passed: int,
        failed: int,
        overall_score: float,
        duration_seconds: float,
    ) -> None:
        """Print the final summary line."""
        status_color = "green" if failed == 0 else "red"
        status_icon = "✅" if failed == 0 else "❌"
        status_word = "PASSED" if failed == 0 else "FAILED"

        summary = Text()
        summary.append(f"\n{status_icon} Overall: ", style=f"bold {status_color}")
        summary.append(f"{status_word}", style=f"bold {status_color}")
        summary.append(f"  ({passed}/{total} passed", style="white")
        summary.append(f", score: {overall_score:.3f}", style="white")
        summary.append(f", {duration_seconds:.1f}s)\n", style="dim")

        console.print(summary)
