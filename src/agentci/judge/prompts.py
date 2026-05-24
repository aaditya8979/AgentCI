"""
Judge prompt templates for LLM-as-a-Judge evaluation.

The three-part prompt architecture: Role & Calibration, Evaluation Context,
and Rubric with structured output format.
"""

JUDGE_SYSTEM_PROMPT = """\
You are an expert quality evaluator for AI agents. You will be given:
1. A scenario describing the situation the agent was placed in
2. The agent's actual response
3. A scoring rubric with specific criteria

Your job is to score the agent's response on EACH criterion from 0.0 to 1.0.

CALIBRATION GUIDE:
- 1.0: The response perfectly satisfies the criterion with no gaps
- 0.8: The response mostly satisfies with only minor, negligible gaps
- 0.5: The response partially satisfies with notable issues or omissions
- 0.2: The response barely addresses the criterion with major problems
- 0.0: The response completely fails or contradicts the criterion

Be precise. Be consistent. Do not let response length influence your scoring \
unless the rubric explicitly rewards detail. Judge ONLY against the rubric criteria \
provided — do not invent additional standards."""


def build_judge_prompt(
    scenario_description: str,
    conversation_history: str,
    agent_output: str,
    rubric_criteria: list[dict],
    context: str | None = None,
) -> str:
    """
    Build the complete evaluation prompt for an LLM judge.

    Args:
        scenario_description: What the scenario is testing.
        conversation_history: The full conversation leading to the agent's response.
        agent_output: The agent's final response to evaluate.
        rubric_criteria: List of dicts with 'name', 'description', 'weight'.
        context: Optional RAG/tool context available to the agent.

    Returns:
        Formatted prompt string.
    """
    criteria_block = "\n".join(
        f"  {i+1}. **{c['name']}** (weight: {c['weight']}): {c['description']}"
        for i, c in enumerate(rubric_criteria)
    )

    context_block = ""
    if context:
        context_block = f"\n\nCONTEXT AVAILABLE TO THE AGENT:\n{context}"

    criteria_json_keys = ", ".join(
        f'"{c["name"]}": {{"score": <0.0-1.0>, "reasoning": "<your reasoning>"}}'
        for c in rubric_criteria
    )

    return f"""\
SCENARIO: {scenario_description}

CONVERSATION:
{conversation_history}

AGENT RESPONSE TO EVALUATE:
{agent_output}{context_block}

CRITERIA TO EVALUATE:
{criteria_block}

Respond ONLY with valid JSON in this exact format (no markdown fences):
{{
  "scores": {{
    {criteria_json_keys}
  }},
  "overall_assessment": "<2-3 sentence summary of the response quality>",
  "confidence": <0.0-1.0 your confidence in this evaluation>
}}"""


TIEBREAKER_SYSTEM_PROMPT = """\
You are a senior evaluator resolving a disagreement between junior evaluators. \
You will see the original scenario, the agent's response, the rubric, AND \
the conflicting evaluations from other judges. Review their reasoning carefully, \
then provide your own independent evaluation. Do not simply average their scores — \
determine the correct score based on the evidence."""


def build_tiebreaker_prompt(
    base_prompt: str,
    judge_evaluations: list[dict],
) -> str:
    """
    Build a tiebreaker prompt that includes prior judges' reasoning.

    Args:
        base_prompt: The original evaluation prompt.
        judge_evaluations: List of prior judge responses with their scores and reasoning.

    Returns:
        Formatted tiebreaker prompt.
    """
    evals_block = "\n\n".join(
        f"--- JUDGE {i+1} ---\n"
        f"Overall: {e.get('overall_assessment', 'N/A')}\n"
        f"Scores: {e.get('scores', {})}"
        for i, e in enumerate(judge_evaluations)
    )

    return f"""\
{base_prompt}

PRIOR EVALUATIONS (for reference — you may disagree):
{evals_block}

Now provide YOUR independent evaluation in the same JSON format."""
