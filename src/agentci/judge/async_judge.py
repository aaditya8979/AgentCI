"""
Async LLM Judge implementation.

Mirrors llm_judge.py but uses httpx.AsyncClient for non-blocking API calls.
Enables parallel judge execution within the consensus panel.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

import httpx

from ..models.scenario import JudgeResponse, ScoreBreakdown
from .llm_judge import JudgeModel
from .prompts import JUDGE_SYSTEM_PROMPT, build_judge_prompt

logger = logging.getLogger(__name__)

# Provider base URLs and defaults
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_GOOGLE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_OLLAMA_DEFAULT_HOST = "http://localhost:11434"


class AsyncLLMJudge:
    """
    Async LLM judge that evaluates agent outputs using httpx.

    Uses raw HTTP calls instead of SDK clients so we can run
    all judges concurrently with asyncio.gather().
    """

    def __init__(self, model: JudgeModel | str, temperature: float = 0.1):
        self.model = model if isinstance(model, str) else model.value
        self.temperature = temperature
        self._client: httpx.AsyncClient | None = None

    @property
    def provider(self) -> str:
        if self.model.startswith("ollama/"):
            return "ollama"
        if self.model.startswith("gpt"):
            return "openai"
        elif self.model.startswith("claude"):
            return "anthropic"
        elif self.model.startswith("gemini"):
            return "google"
        raise ValueError(f"Unknown provider for model: {self.model}")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def evaluate(
        self,
        scenario_description: str,
        conversation_history: str,
        agent_output: str,
        rubric_criteria: list[dict],
        context: str | None = None,
        run_id: str | None = None,
        scenario_id: str | None = None,
    ) -> JudgeResponse:
        """Score an agent's output against a rubric asynchronously."""
        call_id = str(uuid.uuid4())
        user_prompt = build_judge_prompt(
            scenario_description=scenario_description,
            conversation_history=conversation_history,
            agent_output=agent_output,
            rubric_criteria=rubric_criteria,
            context=context,
        )

        start = time.perf_counter()
        raw = await self._call_llm(JUDGE_SYSTEM_PROMPT, user_prompt)
        latency_ms = int((time.perf_counter() - start) * 1000)

        # Estimate token counts (rough: 4 chars ≈ 1 token)
        input_tokens = (len(JUDGE_SYSTEM_PROMPT) + len(user_prompt)) // 4
        output_tokens = len(raw) // 4

        from .pricing import compute_cost, format_cost
        cost_usd = compute_cost(self.provider, self.model, input_tokens, output_tokens)

        logger.info(
            "judge_call_completed",
            extra={
                "call_id": call_id,
                "run_id": run_id,
                "scenario_id": scenario_id,
                "provider": self.provider,
                "model": self.model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost_usd,
                "latency_ms": latency_ms,
            },
        )

        response = self._parse_response(raw, rubric_criteria)
        response.cost_usd = cost_usd
        response.latency_ms = latency_ms
        response.input_tokens = input_tokens
        response.output_tokens = output_tokens
        return response

    async def _call_llm(self, system: str, user: str) -> str:
        if self.provider == "openai":
            return await self._call_openai(system, user)
        elif self.provider == "anthropic":
            return await self._call_anthropic(system, user)
        elif self.provider == "google":
            return await self._call_google(system, user)
        elif self.provider == "ollama":
            return await self._call_ollama(system, user)
        raise ValueError(f"Unsupported provider: {self.provider}")

    async def _call_openai(self, system: str, user: str) -> str:
        import os
        client = await self._get_client()
        resp = await client.post(
            _OPENAI_URL,
            headers={
                "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "temperature": self.temperature,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "response_format": {"type": "json_object"},
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def _call_anthropic(self, system: str, user: str) -> str:
        import os
        client = await self._get_client()
        resp = await client.post(
            _ANTHROPIC_URL,
            headers={
                "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 2048,
                "temperature": self.temperature,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]

    async def _call_google(self, system: str, user: str) -> str:
        import os
        client = await self._get_client()
        url = f"{_GOOGLE_URL}/{self.model}:generateContent?key={os.environ['GOOGLE_API_KEY']}"
        resp = await client.post(
            url,
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": f"{system}\n\n{user}"}]}],
                "generationConfig": {"temperature": self.temperature},
            },
        )
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]

    async def _call_ollama(self, system: str, user: str) -> str:
        import os
        host = os.environ.get("OLLAMA_HOST", _OLLAMA_DEFAULT_HOST)
        model_name = self.model.removeprefix("ollama/")
        client = await self._get_client()
        resp = await client.post(
            f"{host}/api/chat",
            json={
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": self.temperature},
            },
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    def _parse_response(self, raw: str, criteria: list[dict]) -> JudgeResponse:
        """Parse raw LLM output into a structured JudgeResponse."""
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Judge %s returned invalid JSON, using fallback", self.model)
            return JudgeResponse(
                scores={c["name"]: ScoreBreakdown(score=0.5, reasoning="Parse error") for c in criteria},
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
                scores[name] = ScoreBreakdown(score=0.5, reasoning="Not evaluated")

        return JudgeResponse(
            scores=scores,
            overall_assessment=str(data.get("overall_assessment", "")),
            confidence=max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
        )
