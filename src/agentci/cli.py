"""
AgentCI CLI — the primary developer interface.

Commands:
    agentci eval       Run evaluation scenarios against an agent
    agentci init       Initialize AgentCI in a project directory
    agentci validate   Validate scenario files against schema
    agentci baseline   Manage baseline score history
"""
from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .config import AgentCIConfig
from .judge.consensus import ConsensusPanel
from .judge.llm_judge import JudgeModel
from .models.scenario import Scenario, ScenarioResult
from .reporter.console import ConsoleReporter
from .reporter.markdown import MarkdownReporter
from .runner.agent_runner import AgentRunner
from .stats.baseline import BaselineStore
from .stats.significance import is_regression

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True, show_time=False)],
)
logger = logging.getLogger("agentci")
console = Console()

DEFAULT_BASELINE_DIR = ".agentci/baselines"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_scenarios(path: str | Path) -> list[Scenario]:
    """Load scenarios from a JSON file or directory of JSON files."""
    p = Path(path)
    scenarios: list[Scenario] = []

    if p.is_file():
        with p.open() as f:
            data = json.load(f)
        if isinstance(data, list):
            scenarios = [Scenario(**s) for s in data]
        else:
            scenarios = [Scenario(**data)]
    elif p.is_dir():
        for json_file in sorted(p.glob("*.json")):
            with json_file.open() as f:
                data = json.load(f)
            if isinstance(data, list):
                scenarios.extend(Scenario(**s) for s in data)
            else:
                scenarios.append(Scenario(**data))
    else:
        raise click.BadParameter(f"Scenarios path does not exist: {p}")

    return scenarios


def _check_api_key(provider: str) -> bool:
    """Check if the API key for a provider is set. Returns True if present."""
    import os
    env_vars = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GOOGLE_API_KEY",
    }
    var = env_vars.get(provider, "")
    return bool(os.environ.get(var, "").strip())


def _validate_api_keys(models: list[str]) -> list[str]:
    """Validate API keys for the requested judge models. Returns list of errors."""
    errors = []
    env_vars = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GOOGLE_API_KEY",
    }
    needed = set()
    for m in models:
        if m.startswith("gpt"):
            needed.add("openai")
        elif m.startswith("claude"):
            needed.add("anthropic")
        elif m.startswith("gemini"):
            needed.add("google")

    for provider in needed:
        if not _check_api_key(provider):
            var = env_vars[provider]
            errors.append(f"{provider.capitalize()} ({var}) — not set or empty")
    return errors


def _build_panel(judges: int) -> tuple[ConsensusPanel, list[str]]:
    """Build a judge panel and return the model name list."""
    if judges >= 3:
        models = [JudgeModel.GPT_4O, JudgeModel.CLAUDE_SONNET, JudgeModel.GEMINI_PRO]
    elif judges == 2:
        models = [JudgeModel.GPT_4O, JudgeModel.CLAUDE_SONNET]
    else:
        models = [JudgeModel.GPT_4O]
    return ConsensusPanel(models=models), [m.value if hasattr(m, "value") else m for m in models]


def _build_json_output(
    results: list[ScenarioResult],
    regressions: dict,
    agent_path: str,
    scenarios_path: str,
    duration: float,
) -> dict:
    """Build the JSON output dict for --format json."""
    total = len(results)
    avg = sum(r.weighted_score for r in results) / total if total else 0.0
    failed = sum(1 for r in results if not r.passed)

    scenarios_out = []
    for r in results:
        reg = regressions.get(r.scenario_id)
        scenarios_out.append({
            "scenario_id": r.scenario_id,
            "score": round(r.weighted_score, 4),
            "baseline": round(reg.baseline_mean, 4) if reg else None,
            "delta": round(reg.delta, 4) if reg else None,
            "p_value": round(reg.p_value, 4) if reg else None,
            "passed": r.passed,
            "scores": {k: round(v, 4) for k, v in r.scores.items()},
            "regression": reg.severity.value if reg and reg.is_regression else None,
        })

    return {
        "run_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_path": agent_path,
        "scenarios_file": scenarios_path,
        "overall_passed": failed == 0,
        "overall_score": round(avg, 4),
        "scenarios_total": total,
        "scenarios_passed": total - failed,
        "duration_seconds": round(duration, 2),
        "scenarios": scenarios_out,
    }


# ── Commands ─────────────────────────────────────────────────────────────────

@click.group()
@click.version_option(version="0.2.0", prog_name="agentci")
def main():
    """⚡ AgentCI — Enterprise-Grade CI/CD Quality Gate for LLM Agents.

    AgentCI evaluates your LLM agents by running them against predefined scenarios
    and judging their outputs using a panel of multiple LLMs (GPT-4o, Claude, Gemini).
    
    It prevents regressions, hallucinations, and safety violations from reaching production
    by applying statistical rigor (Welch's t-test) to score changes.
    """
    pass


@main.command()
@click.option("--agent", "-a", required=True, type=click.Path(exists=True),
              help="Path to the agent script.")
@click.option("--scenarios", "-s", required=True, type=click.Path(exists=True),
              help="Path to scenarios JSON file or directory.")
@click.option("--function", "-f", default="run", show_default=True,
              help="Entry function name in the agent module.")
@click.option("--judges", "-j", default=1, show_default=True, type=click.IntRange(1, 5),
              help="Number of judges (1=single, 3=full panel).")
@click.option("--runs", "-r", default=1, show_default=True, type=click.IntRange(1, 20),
              help="Repeated runs per scenario for stability.")
@click.option("--threshold", default=0.85, show_default=True, type=click.FloatRange(0.0, 1.0),
              help="Minimum score to pass.")
@click.option("--output", "-o", type=click.Path(), help="Write markdown report to file.")
@click.option("--config", "-c", type=click.Path(exists=True), help=".agentci.yml config file.")
@click.option("--format", "fmt", type=click.Choice(["rich", "json"]), default="rich",
              show_default=True, help="Output format.")
@click.option("--dry-run", is_flag=True, help="Run agent only, skip judge calls.")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def eval(agent, scenarios, function, judges, runs, threshold, output, config, fmt, dry_run, verbose):
    """Run evaluation scenarios against an agent and produce a quality report."""
    if verbose:
        logging.getLogger("agentci").setLevel(logging.DEBUG)

    quiet = fmt == "json"
    reporter = ConsoleReporter()
    baseline_store = BaselineStore(DEFAULT_BASELINE_DIR)

    if not quiet:
        mode = "Dry Run" if dry_run else "Evaluation"
        reporter.print_header(mode, f"Agent: {agent}")

    # Load scenarios
    try:
        scenario_list = _load_scenarios(scenarios)
    except Exception as e:
        if quiet:
            print(json.dumps({"error": str(e)}))
        else:
            console.print(Panel(f"[red]Error loading scenarios:[/red] {e}", border_style="red"))
        sys.exit(1)

    if not quiet:
        click.echo(f"  Loaded {len(scenario_list)} scenario(s)")

    # Load agent
    runner = AgentRunner(agent_path=agent, agent_function=function)
    try:
        runner.load()
    except Exception as e:
        if quiet:
            print(json.dumps({"error": str(e)}))
        else:
            console.print(Panel(f"[red]Error loading agent:[/red] {e}", border_style="red"))
        sys.exit(1)

    # ── DRY RUN MODE ─────────────────────────────────────────────────────
    if dry_run:
        if not quiet:
            click.echo("  Mode: DRY RUN (no judge calls)\n")

        start_time = time.time()
        for i, scenario in enumerate(scenario_list, 1):
            agent_output, trace = runner.run_scenario(scenario)
            if not quiet:
                click.echo(f"  [{i}/{len(scenario_list)}] {scenario.scenario_id}")
                click.echo(f"    Output: {agent_output[:120]}...")
                click.echo(f"    Trace: {len(trace.steps)} steps, {trace.total_latency_ms:.0f}ms\n")

        duration = time.time() - start_time
        if not quiet:
            console.print(Panel(
                f"[cyan]Dry run complete.[/cyan] {len(scenario_list)} scenarios executed in "
                f"{duration:.1f}s. No scoring performed.",
                border_style="cyan",
            ))
        else:
            print(json.dumps({
                "mode": "dry_run",
                "scenarios_executed": len(scenario_list),
                "duration_seconds": round(duration, 2),
            }))
        sys.exit(0)

    # ── FULL EVAL MODE ───────────────────────────────────────────────────

    # Validate API keys before spending time on evals
    panel, model_names = _build_panel(judges)
    key_errors = _validate_api_keys(model_names)
    if key_errors:
        if quiet:
            print(json.dumps({"error": "Missing API keys", "details": key_errors}))
        else:
            error_text = Text()
            error_text.append("❌ Judge Configuration Error\n\n", style="bold red")
            error_text.append("The following API keys are missing:\n", style="white")
            for err in key_errors:
                error_text.append(f"  • {err}\n", style="yellow")
            error_text.append("\nSet them in your environment before running eval.", style="dim")
            console.print(Panel(error_text, border_style="red"))
        sys.exit(1)

    if not quiet:
        click.echo(f"  Judge panel: {', '.join(model_names)}")
        click.echo(f"  Runs per scenario: {runs}")
        click.echo()

    start_time = time.time()
    results: list[ScenarioResult] = []

    for i, scenario in enumerate(scenario_list, 1):
        if not quiet:
            click.echo(f"  [{i}/{len(scenario_list)}] Running: {scenario.scenario_id}...", nl=False)

        try:
            agent_output, trace = runner.run_scenario(scenario)
            conv_text = "\n".join(f"[{m.role.upper()}]: {m.content}" for m in scenario.conversation)
            rubric_dicts = [
                {"name": c.name, "description": c.description, "weight": c.weight}
                for c in scenario.rubric.criteria
            ]
            context_str = json.dumps(scenario.context) if scenario.context else None

            consensus = panel.evaluate(
                scenario_description=scenario.description,
                conversation_history=conv_text,
                agent_output=agent_output,
                rubric_criteria=rubric_dicts,
                context=context_str,
            )

            passed = consensus.weighted_score >= (scenario.rubric.passing_threshold or threshold)
            result = ScenarioResult(
                scenario_id=scenario.scenario_id,
                scores=consensus.consensus_scores,
                weighted_score=consensus.weighted_score,
                passed=passed,
                trace=trace,
                judge_reasonings={
                    f"judge_{j}": resp.overall_assessment
                    for j, resp in enumerate(consensus.individual_responses)
                },
            )
            results.append(result)

            if not quiet:
                status = "✅" if passed else "❌"
                click.echo(f" {status} {consensus.weighted_score:.3f}")

        except Exception as e:
            if not quiet:
                click.echo(f" 💥 Error: {e}")
            logger.exception("Scenario %s failed", scenario.scenario_id)

    duration = time.time() - start_time

    # ── Baseline comparison ──────────────────────────────────────────────
    regressions = {}
    for r in results:
        baseline_scores = baseline_store.get_baseline_scores(r.scenario_id, window=10)
        if len(baseline_scores) >= 3:
            reg = is_regression(baseline_scores, [r.weighted_score] * max(runs, 3))
            regressions[r.scenario_id] = reg
        # Store new score
        baseline_store.append_score(r.scenario_id, r.weighted_score)

    # ── Output ───────────────────────────────────────────────────────────
    total = len(results)
    passed_count = sum(1 for r in results if r.passed)
    failed_count = total - passed_count
    avg_score = sum(r.weighted_score for r in results) / total if total else 0.0

    if quiet:
        print(json.dumps(_build_json_output(results, regressions, agent, scenarios, duration), indent=2))
    else:
        click.echo()
        reporter.print_scenario_table(results, regressions)
        for r in results:
            if not r.passed:
                reporter.print_failure_details(r, regressions.get(r.scenario_id))
        reporter.print_summary(total, passed_count, failed_count, avg_score, duration)

    if output:
        md = MarkdownReporter.generate_report(results, regressions, duration_seconds=duration)
        Path(output).write_text(md)
        if not quiet:
            click.echo(f"  Report written to {output}")

    sys.exit(1 if failed_count > 0 else 0)


@main.command()
@click.argument("scenarios_path", type=click.Path(exists=True))
def validate(scenarios_path):
    """Validate scenario files against the AgentCI schema."""
    try:
        scenario_list = _load_scenarios(scenarios_path)
    except json.JSONDecodeError as e:
        console.print(Panel(f"[red]Invalid JSON:[/red] {e}", border_style="red"))
        sys.exit(1)
    except Exception as e:
        console.print(Panel(f"[red]Load error:[/red] {e}", border_style="red"))
        sys.exit(1)

    table = Table(title="Scenario Validation", show_header=True, header_style="bold magenta")
    table.add_column("Scenario ID", min_width=30)
    table.add_column("Criteria", justify="center")
    table.add_column("Weight Sum", justify="center")
    table.add_column("Status", justify="center")

    all_valid = True
    seen_ids: set[str] = set()
    errors: list[str] = []

    for s in scenario_list:
        issues: list[str] = []

        # Duplicate check
        if s.scenario_id in seen_ids:
            issues.append(f"Duplicate scenario_id: {s.scenario_id}")
        seen_ids.add(s.scenario_id)

        # Conversation check
        if not s.conversation:
            issues.append("Empty conversation")

        # Criteria checks
        criteria_count = len(s.rubric.criteria)
        if criteria_count == 0:
            issues.append("No rubric criteria")

        weight_sum = sum(c.weight for c in s.rubric.criteria)
        weight_ok = abs(weight_sum - 1.0) <= 0.01

        for c in s.rubric.criteria:
            if not c.name.strip():
                issues.append("Criterion with empty name")
            if not c.description.strip():
                issues.append(f"Criterion '{c.name}' has empty description")
            if not (0.0 <= c.weight <= 1.0):
                issues.append(f"Criterion '{c.name}' weight {c.weight} out of [0,1]")

        if not weight_ok:
            issues.append(f"Weights sum to {weight_sum:.3f}, expected 1.0 ± 0.01")

        if issues:
            all_valid = False
            errors.extend(issues)
            status = Text("❌ FAIL", style="bold red")
        else:
            status = Text("✅ PASS", style="bold green")

        weight_style = "green" if weight_ok else "red"
        table.add_row(
            s.scenario_id,
            str(criteria_count),
            f"[{weight_style}]{weight_sum:.3f}[/{weight_style}]",
            status,
        )

    console.print(table)

    if errors:
        console.print(f"\n[red]Validation failed with {len(errors)} issue(s):[/red]")
        for err in errors:
            console.print(f"  • {err}")

    console.print(f"\n{'✅ All valid' if all_valid else '❌ Errors found'} — "
                  f"{len(scenario_list)} scenario(s) checked")
    sys.exit(0 if all_valid else 1)


@main.group()
def baseline():
    """Manage baseline score history."""
    pass


@baseline.command("list")
@click.option("--dir", "baseline_dir", default=DEFAULT_BASELINE_DIR, help="Baseline storage directory.")
def baseline_list(baseline_dir):
    """List all stored scenario baselines."""
    BaselineStore(baseline_dir)
    base_path = Path(baseline_dir)

    if not base_path.exists():
        click.echo("  No baselines stored yet.")
        return

    files = sorted(base_path.glob("*.json"))
    if not files:
        click.echo("  No baselines stored yet.")
        return

    table = Table(title="Stored Baselines", header_style="bold cyan")
    table.add_column("Scenario ID", min_width=30)
    table.add_column("Samples", justify="center")
    table.add_column("Mean", justify="center")
    table.add_column("Latest", justify="center")

    for f in files:
        try:
            with f.open() as fp:
                data = json.load(fp)
            sid = data.get("scenario_id", f.stem)
            entries = data.get("entries", [])
            scores = [e["weighted_score"] for e in entries]
            mean = sum(scores) / len(scores) if scores else 0
            latest = scores[-1] if scores else 0
            table.add_row(sid, str(len(scores)), f"{mean:.3f}", f"{latest:.3f}")
        except Exception:
            table.add_row(f.stem, "?", "?", "?")

    console.print(table)


@baseline.command("show")
@click.argument("scenario_id")
@click.option("--dir", "baseline_dir", default=DEFAULT_BASELINE_DIR)
def baseline_show(scenario_id, baseline_dir):
    """Show rolling scores for a single scenario."""
    store = BaselineStore(baseline_dir)
    scores = store.get_baseline_scores(scenario_id, window=100)

    if not scores:
        click.echo(f"  No baseline data for '{scenario_id}'")
        return

    click.echo(f"\n  Scenario: {scenario_id}")
    click.echo(f"  Samples:  {len(scores)}")
    click.echo(f"  Mean:     {sum(scores)/len(scores):.4f}")
    click.echo(f"  Scores:   {', '.join(f'{s:.3f}' for s in scores[-20:])}")
    if len(scores) > 20:
        click.echo(f"            (showing last 20 of {len(scores)})")


@baseline.command("clear")
@click.option("--scenario", help="Clear only this scenario's baseline.")
@click.option("--dir", "baseline_dir", default=DEFAULT_BASELINE_DIR)
@click.confirmation_option(prompt="Are you sure you want to clear baselines?")
def baseline_clear(scenario, baseline_dir):
    """Clear baseline data."""
    store = BaselineStore(baseline_dir)
    store.clear(scenario)
    target = f"'{scenario}'" if scenario else "all scenarios"
    click.echo(f"  ✅ Cleared baselines for {target}")


@main.command()
@click.option("--path", "-p", default=".", type=click.Path(), help="Directory to initialize in.")
@click.option("--github-actions", is_flag=True, help="Also generate GitHub Actions workflow.")
def init(path, github_actions):
    """Initialize AgentCI in a project directory with smart defaults."""
    from .enterprise.framework_detector import detect_framework
    from .enterprise.scenario_gen import generate_from_system_prompt, write_scenarios

    project_dir = Path(path).resolve()
    config_path = project_dir / ".agentci.yml"

    if config_path.exists():
        console.print(f"  [yellow]Config already exists:[/yellow] {config_path}")
        if not click.confirm("  Overwrite?"):
            return

    # 1. Detect framework
    console.print("\n  [cyan]Scanning project...[/cyan]")
    detection = detect_framework(project_dir)
    if detection.detected:
        console.print(f"  ✓ {detection.description}")
        if detection.agent_candidates:
            console.print(f"  ✓ Candidate entry points: {', '.join(detection.agent_candidates[:3])}")
    else:
        console.print("  ℹ No specific framework detected, using defaults")

    # 2. Interactive prompts
    from rich.prompt import Prompt
    agent_desc = Prompt.ask("\n  [bold]Describe your agent in one sentence[/bold]",
                           default="An AI assistant")
    use_case = Prompt.ask("  [bold]Primary use case[/bold]",
                          choices=["customer_support", "coding_assistant", "data_analysis", "document_processing", "other"],
                          default="other")
    judge_provider = Prompt.ask("  [bold]Primary LLM provider for judges[/bold]",
                                choices=["openai", "anthropic", "google", "local"],
                                default="openai")

    # 3. Generate config
    cfg = AgentCIConfig(
        agent_entry=detection.recommended_entry,
        agent_function=detection.recommended_function,
        scenarios_path=".agentci/scenarios.json",
    )
    cfg.to_yaml(config_path)
    console.print(f"\n  ✅ Created {config_path}")

    # 4. Generate scenarios
    agentci_dir = project_dir / ".agentci"
    agentci_dir.mkdir(parents=True, exist_ok=True)
    scenarios_path = agentci_dir / "scenarios.json"

    # Try system prompt-based generation
    prompt_candidates = list(project_dir.glob("**/system_prompt*")) + list(project_dir.glob("**/instructions*"))
    if prompt_candidates:
        prompt_text = prompt_candidates[0].read_text()
        scenarios = generate_from_system_prompt(prompt_text, count=20, domain=use_case)
        if scenarios:
            write_scenarios(scenarios, scenarios_path)
            console.print(f"  ✅ Generated {len(scenarios)} scenarios from system prompt")
    
    if not scenarios_path.exists():
        # Fallback: use starter pack
        _copy_starter_pack(use_case, scenarios_path)
        console.print(f"  ✅ Loaded starter pack scenarios for {use_case}")

    # 5. Generate example agent
    agent_example = project_dir / "eval" / "example_agent.py"
    agent_example.parent.mkdir(parents=True, exist_ok=True)
    agent_example.write_text(
        f'"""{agent_desc}"""\n\n\n'
        'def run(input_data: dict) -> str:\n'
        '    messages = input_data.get("messages", [])\n'
        '    last_message = messages[-1]["content"] if messages else ""\n'
        '    return f"Hello! You said: \\"{last_message}\\". How can I help?"\n'
    )
    console.print(f"  ✅ Created {agent_example.relative_to(project_dir)}")

    # 6. Gitignore
    gitignore = project_dir / ".gitignore"
    entries = [".env", ".agentci/baselines/", "__pycache__/"]
    if gitignore.exists():
        content = gitignore.read_text()
        new_entries = [e for e in entries if e not in content]
        if new_entries:
            with gitignore.open("a") as f:
                f.write("\n" + "\n".join(new_entries) + "\n")
    else:
        gitignore.write_text("\n".join(entries) + "\n")

    # 7. GitHub Actions (optional)
    if github_actions:
        from .enterprise.actions_generator import write_actions_workflow
        wf_path = write_actions_workflow(output_dir=project_dir, judge_provider=judge_provider)
        console.print(f"  ✅ Created {wf_path.relative_to(project_dir)}")

    # 8. Success panel
    eval_cmd = f"agentci eval -a {detection.recommended_entry} -s .agentci/scenarios.json --dry-run"
    console.print(Panel(
        f"[green bold]AgentCI is ready.[/green bold]\n\n"
        f"Run this to verify your agent loads correctly:\n"
        f"  [cyan]{eval_cmd}[/cyan]\n\n"
        f"Then remove --dry-run to score with real judges.",
        border_style="green",
        title="🎉 Setup Complete",
    ))


def _copy_starter_pack(domain: str, output_path: Path) -> None:
    """Copy a starter pack to the project's scenario file."""
    pack_dir = Path(__file__).parent / "enterprise" / "starter_packs"
    domain_map = {
        "customer_support": "customer_support.json",
        "coding_assistant": "coding.json",
        "data_analysis": "customer_support.json",  # fallback
        "document_processing": "customer_support.json",  # fallback
        "other": "customer_support.json",
    }
    pack_file = pack_dir / domain_map.get(domain, "customer_support.json")
    if pack_file.exists():
        output_path.write_text(pack_file.read_text())
    else:
        # Write minimal example
        output_path.write_text(json.dumps([{
            "scenario_id": "example_001",
            "description": "Basic greeting test",
            "category": "general",
            "difficulty": "easy",
            "conversation": [{"role": "user", "content": "Hello!"}],
            "rubric": {
                "criteria": [
                    {"name": "politeness", "description": "Responds politely", "weight": 0.5},
                    {"name": "relevance", "description": "Response is relevant", "weight": 0.5},
                ],
                "passing_threshold": 0.8,
            },
        }], indent=2))


# ── generate ─────────────────────────────────────────────────────────────────

@main.command()
@click.option("--system-prompt", type=click.Path(exists=True), help="Path to system prompt file.")
@click.option("--from-logs", type=click.Path(exists=True), help="Path to production logs (JSONL).")
@click.option("--count", default=20, type=int, help="Number of scenarios to generate.")
@click.option("--domain", default="other", help="Domain context for generation.")
@click.option("--output", "-o", required=True, type=click.Path(), help="Output path for scenarios JSON.")
def generate(system_prompt, from_logs, count, domain, output):
    """Generate eval scenarios from system prompts or production logs."""
    from .enterprise.scenario_gen import generate_from_system_prompt, generate_from_logs, write_scenarios

    if system_prompt:
        prompt_text = Path(system_prompt).read_text()
        scenarios = generate_from_system_prompt(prompt_text, count=count, domain=domain)
        source = "system prompt"
    elif from_logs:
        scenarios = generate_from_logs(from_logs, count=count, domain=domain)
        source = "production logs"
    else:
        console.print("[red]Specify --system-prompt or --from-logs[/red]")
        sys.exit(1)

    write_scenarios(scenarios, output)
    console.print(f"  ✅ Generated {len(scenarios)} scenarios from {source} → {output}")

    # Summary table
    cats: dict[str, int] = {}
    for s in scenarios:
        cats[s.category] = cats.get(s.category, 0) + 1
    table = Table(title="Generation Summary", header_style="bold cyan")
    table.add_column("Category")
    table.add_column("Count", justify="center")
    for cat, cnt in sorted(cats.items()):
        table.add_row(cat, str(cnt))
    console.print(table)


# ── starter-pack ─────────────────────────────────────────────────────────────

@main.command("starter-pack")
@click.option("--domain", required=True,
              type=click.Choice(["fintech", "legal", "healthcare", "coding", "customer_support"]),
              help="Domain for the starter pack.")
@click.option("--output", "-o", required=True, type=click.Path(), help="Output path.")
def starter_pack(domain, output):
    """Load a pre-built scenario pack for a specific domain."""
    pack_dir = Path(__file__).parent / "enterprise" / "starter_packs"
    pack_file = pack_dir / f"{domain}.json"
    if not pack_file.exists():
        console.print(f"[red]Starter pack not found: {domain}[/red]")
        sys.exit(1)
    import shutil
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pack_file, output)
    data = json.loads(pack_file.read_text())
    console.print(f"  ✅ Loaded {len(data)} scenarios from {domain} starter pack → {output}")


# ── keys ─────────────────────────────────────────────────────────────────────

@main.group()
def keys():
    """Manage API keys for BYOK operation."""
    pass


@keys.command("check")
def keys_check():
    """Validate all configured API keys."""
    from .enterprise.keys import check_all_keys, detect_ollama

    statuses = check_all_keys()
    table = Table(title="API Key Status", header_style="bold cyan")
    table.add_column("Provider")
    table.add_column("Env Var")
    table.add_column("Found")
    table.add_column("Source")

    for s in statuses:
        found_icon = "✅" if s.found else "❌"
        table.add_row(s.provider, s.env_var, found_icon, s.source)

    console.print(table)

    if detect_ollama():
        console.print("  ℹ [cyan]Ollama detected[/cyan] at localhost:11434 — local judge available")
    else:
        console.print("  ℹ [dim]Ollama not detected[/dim]")


@keys.command("set")
@click.option("--provider", required=True, type=click.Choice(["openai", "anthropic", "google"]))
def keys_set(provider):
    """Set an API key for a provider (saved to .env)."""
    from .enterprise.keys import validate_key, save_key_to_dotenv
    key = click.prompt(f"  Enter {provider} API key", hide_input=True)
    console.print("  Validating...", end="")
    valid, err = validate_key(provider, key)
    if valid:
        save_key_to_dotenv(provider, key)
        console.print(" ✅ Valid — saved to .env")
    else:
        console.print(f" ❌ Invalid: {err}")
        if click.confirm("  Save anyway?"):
            save_key_to_dotenv(provider, key)


# ── status ───────────────────────────────────────────────────────────────────

@main.command()
def status():
    """Check health of all AgentCI services."""
    import httpx as _httpx

    services = {
        "api": "http://localhost:8000/health",
        "dashboard": "http://localhost:3000",
        "temporal": "http://localhost:7233",
        "temporal-ui": "http://localhost:8080",
    }

    table = Table(title="Service Health", header_style="bold cyan")
    table.add_column("Service")
    table.add_column("Endpoint")
    table.add_column("Status")

    all_healthy = True
    for name, url in services.items():
        try:
            resp = _httpx.get(url, timeout=3)
            if resp.status_code < 500:
                table.add_row(name, url, "[green]✓ healthy[/green]")
            else:
                table.add_row(name, url, f"[red]✗ {resp.status_code}[/red]")
                all_healthy = False
        except Exception:
            table.add_row(name, url, "[red]✗ unreachable[/red]")
            all_healthy = False

    console.print(table)
    if not all_healthy:
        console.print("\n  [yellow]Some services are down. Run:[/yellow]")
        console.print("  docker compose -f docker/docker-compose-adoption.yml up -d")


# ── attest ───────────────────────────────────────────────────────────────────

@main.command()
@click.option("--run-id", required=True, help="Eval run ID to attest.")
@click.option("--repo", default="", help="Repository name.")
@click.option("--output", "-o", default="attestation.json", help="Output file path.")
def attest(run_id, repo, output):
    """Generate a signed eval attestation document."""
    from .enterprise.governance import create_attestation, save_attestation

    att = create_attestation(run_id=run_id, repo=repo)
    save_attestation(att, output)
    console.print(f"  ✅ Attestation saved to {output}")
    console.print(f"  Signature: {att.signature[:16]}...")
    console.print(f"  Verify with: agentci attest-verify --file {output}")


@main.command("attest-verify")
@click.option("--file", "attestation_file", required=True, type=click.Path(exists=True))
def attest_verify(attestation_file):
    """Verify a signed attestation document."""
    from .enterprise.governance import load_and_verify

    att, is_valid = load_and_verify(attestation_file)
    if is_valid:
        console.print("  ✅ [green]VALID[/green] — attestation signature verified")
        console.print(f"  Run: {att.run_id}  Score: {att.overall_score}  Outcome: {att.outcome}")
    else:
        console.print("  ❌ [red]TAMPERED[/red] — signature does not match")
        sys.exit(1)


# ── compliance ───────────────────────────────────────────────────────────────

@main.command("compliance")
@click.argument("action", type=click.Choice(["list", "show"]))
@click.argument("template_name", required=False)
def compliance(action, template_name):
    """List or show compliance templates."""
    import yaml as _yaml
    compliance_dir = Path(__file__).parent / "enterprise" / "compliance"

    if action == "list":
        table = Table(title="Compliance Templates", header_style="bold cyan")
        table.add_column("Template")
        table.add_column("Framework")
        for f in sorted(compliance_dir.glob("*.yaml")):
            data = _yaml.safe_load(f.read_text())
            table.add_row(data.get("name", f.stem), data.get("framework", "—"))
        console.print(table)

    elif action == "show":
        if not template_name:
            console.print("[red]Specify template name[/red]")
            sys.exit(1)
        f = compliance_dir / f"{template_name}.yaml"
        if not f.exists():
            console.print(f"[red]Template not found: {template_name}[/red]")
            sys.exit(1)
        data = _yaml.safe_load(f.read_text())
        console.print(f"\n  [bold]{data.get('name')}[/bold] — {data.get('framework')}\n")
        for c in data.get("criteria", []):
            console.print(f"  • [cyan]{c['name']}[/cyan] (weight: {c['weight']})")
            console.print(f"    {c['description']}")


if __name__ == "__main__":
    main()

