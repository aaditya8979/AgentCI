"""
LLM-as-a-Judge implementation.

Supports OpenAI, Anthropic, and Google Gemini as judge backends.
Each judge scores an agent's output against a rubric independently.
"""
from __future__ import annotations

import json
import logging
from enum import Enum

from ..models.scenario import JudgeResponse, ScoreBreakdown
from .prompts import JUDGE_SYSTEM_PROMPT, build_judge_prompt

logger = logging.getLogger(__name__)


class JudgeModel(str, Enum):
    """Supported judge model backends."""
    GPT_4O = "gpt-4o"
    GPT_4O_MINI = "gpt-4o-mini"
    CLAUDE_SONNET = "claude-sonnet-4-20250514"
    CLAUDE_HAIKU = "claude-haiku-4-20250514"
    GEMINI_PRO = "gemini-2.5-pro"
    GEMINI_FLASH = "gemini-2.5-flash"


class LLMJudge:
    """
    A single LLM judge that evaluates agent outputs against a rubric.

    Each judge wraps one LLM provider and handles prompt construction,
    API calls, and response parsing into structured JudgeResponse objects.
    """

    def __init__(self, model: JudgeModel | str, temperature: float = 0.1):
        self.model = model if isinstance(model, str) else model.value
        self.temperature = temperature
        self._client = None

    @property
    def provider(self) -> str:
        if self.model.startswith("gpt"):
            return "openai"
        elif self.model.startswith("claude"):
            return "anthropic"
        elif self.model.startswith("gemini"):
            return "google"
        else:
            raise ValueError(f"Unknown model provider for: {self.model}")

    def _get_openai_client(self):
        """Lazily initialise the OpenAI client."""
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI()
        return self._client

    def _get_anthropic_client(self):
        if self._client is None:
            from anthropic import Anthropic
            self._client = Anthropic()
        return self._client

    def _get_google_client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client()
        return self._client

    def evaluate(
        self,
        scenario_description: str,
        conversation_history: str,
        agent_output: str,
        rubric_criteria: list[dict],
        context: str | None = None,
    ) -> JudgeResponse:
        """
        Score an agent's output against a rubric using this judge model.

        Args:
            scenario_description: What the scenario is testing.
            conversation_history: The conversation that led to the agent's response.
            agent_output: The agent's response to evaluate.
            rubric_criteria: List of criterion dicts with name, description, weight.
            context: Optional context the agent had access to.

        Returns:
            Parsed JudgeResponse with per-criterion scores and reasoning.
        """
        user_prompt = build_judge_prompt(
            scenario_description=scenario_description,
            conversation_history=conversation_history,
            agent_output=agent_output,
            rubric_criteria=rubric_criteria,
            context=context,
        )

        raw = self._call_llm(JUDGE_SYSTEM_PROMPT, user_prompt)
        return self._parse_response(raw, rubric_criteria)

    def _call_llm(self, system: str, user: str) -> str:
        """Dispatch to the correct provider."""
        if self.provider == "openai":
            return self._call_openai(system, user)
        elif self.provider == "anthropic":
            return self._call_anthropic(system, user)
        elif self.provider == "google":
            return self._call_google(system, user)
        raise ValueError(f"Unsupported provider: {self.provider}")

    def _call_openai(self, system: str, user: str) -> str:
        client = self._get_openai_client()
        resp = client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content

    def _call_anthropic(self, system: str, user: str) -> str:
        client = self._get_anthropic_client()
        resp = client.messages.create(
            model=self.model,
            max_tokens=2048,
            temperature=self.temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text

    def _call_google(self, system: str, user: str) -> str:
        client = self._get_google_client()
        resp = client.models.generate_content(
            model=self.model,
            contents=f"{system}\n\n{user}",
            config={"temperature": self.temperature},
        )
        return resp.text

    def _parse_response(self, raw: str, criteria: list[dict]) -> JudgeResponse:
        """Parse the raw LLM output into a structured JudgeResponse."""
        # Strip markdown fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Judge %s returned invalid JSON, using fallback scores", self.model)
            fallback_scores = {
                c["name"]: ScoreBreakdown(score=0.5, reasoning="Parse error — fallback score")
                for c in criteria
            }
            return JudgeResponse(
                scores=fallback_scores,
                overall_assessment="Failed to parse judge response",
                confidence=0.0,
            )

        scores = {}
        raw_scores = data.get("scores", {})
        for c in criteria:
            name = c["name"]
            if name in raw_scores and isinstance(raw_scores[name], dict):
                scores[name] = ScoreBreakdown(
                    score=max(0.0, min(1.0, float(raw_scores[name].get("score", 0.5)))),
                    reasoning=str(raw_scores[name].get("reasoning", "")),
                )
            else:
                scores[name] = ScoreBreakdown(score=0.5, reasoning="Criterion not evaluated by judge")

        return JudgeResponse(
            scores=scores,
            overall_assessment=str(data.get("overall_assessment", "")),
            confidence=max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
        )
