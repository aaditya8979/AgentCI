"""
Agent Adapter Protocol — unified interface for running any agent.

Provides a Protocol class and concrete adapters for:
  - Python functions (existing behavior)
  - HTTP REST API agents
  - LangChain AgentExecutors
  - MCP-compatible agent servers
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)


@dataclass
class AgentInput:
    """Standardized input to any agent adapter."""
    conversation: list[dict[str, str]]
    context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentOutput:
    """Standardized output from any agent adapter."""
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class AgentAdapter(Protocol):
    """Protocol all agent adapters must implement."""

    def run(self, input: AgentInput) -> AgentOutput: ...
    async def run_async(self, input: AgentInput) -> AgentOutput: ...
    def stream(self, input: AgentInput) -> Iterator[str]: ...
    def reset(self) -> None: ...
    def health_check(self) -> bool: ...


class PythonFunctionAdapter:
    """
    Wraps a plain Python function: run(input: str | dict) -> str.

    This is the default adapter matching AgentCI v0.1 behavior.
    """

    def __init__(self, func: Any):
        self._func = func

    def run(self, input: AgentInput) -> AgentOutput:
        input_dict = {
            "messages": input.conversation,
            "context": input.context,
        }
        result = self._func(input_dict)
        content = result if isinstance(result, str) else str(result)
        return AgentOutput(content=content)

    async def run_async(self, input: AgentInput) -> AgentOutput:
        return self.run(input)

    def stream(self, input: AgentInput) -> Iterator[str]:
        result = self.run(input)
        yield result.content

    def reset(self) -> None:
        pass

    def health_check(self) -> bool:
        return True


class HTTPAdapter:
    """
    Calls any agent via its REST API endpoint.

    Expects a POST endpoint that accepts JSON with conversation and context,
    and returns JSON with a 'content' field.
    """

    def __init__(
        self,
        endpoint: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ):
        self.endpoint = endpoint
        self.headers = headers or {"Content-Type": "application/json"}
        self.timeout = timeout

    def run(self, input: AgentInput) -> AgentOutput:
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                self.endpoint,
                headers=self.headers,
                json={
                    "conversation": input.conversation,
                    "context": input.context,
                    "metadata": input.metadata,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return AgentOutput(
                content=data.get("content", data.get("response", str(data))),
                tool_calls=data.get("tool_calls", []),
                metadata=data.get("metadata", {}),
            )

    async def run_async(self, input: AgentInput) -> AgentOutput:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                self.endpoint,
                headers=self.headers,
                json={
                    "conversation": input.conversation,
                    "context": input.context,
                    "metadata": input.metadata,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return AgentOutput(
                content=data.get("content", data.get("response", str(data))),
                tool_calls=data.get("tool_calls", []),
                metadata=data.get("metadata", {}),
            )

    def stream(self, input: AgentInput) -> Iterator[str]:
        result = self.run(input)
        yield result.content

    def reset(self) -> None:
        pass

    def health_check(self) -> bool:
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(self.endpoint.rsplit("/", 1)[0] + "/health")
                return resp.status_code == 200
        except Exception:
            return False


class LangChainAdapter:
    """
    Wraps a LangChain AgentExecutor.

    Lazily imports langchain to avoid hard dependency.
    """

    def __init__(self, executor: Any):
        self._executor = executor

    def run(self, input: AgentInput) -> AgentOutput:
        last_msg = input.conversation[-1]["content"] if input.conversation else ""
        result = self._executor.invoke({"input": last_msg})
        content = result.get("output", str(result)) if isinstance(result, dict) else str(result)
        return AgentOutput(content=content)

    async def run_async(self, input: AgentInput) -> AgentOutput:
        last_msg = input.conversation[-1]["content"] if input.conversation else ""
        result = await self._executor.ainvoke({"input": last_msg})
        content = result.get("output", str(result)) if isinstance(result, dict) else str(result)
        return AgentOutput(content=content)

    def stream(self, input: AgentInput) -> Iterator[str]:
        result = self.run(input)
        yield result.content

    def reset(self) -> None:
        pass

    def health_check(self) -> bool:
        return self._executor is not None


class MCPAdapter:
    """
    Communicates with any MCP-compatible agent server.

    Sends tool/resource requests via the MCP protocol over HTTP.
    """

    def __init__(self, server_url: str, timeout: float = 30.0):
        self.server_url = server_url
        self.timeout = timeout

    def run(self, input: AgentInput) -> AgentOutput:
        last_msg = input.conversation[-1]["content"] if input.conversation else ""
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.server_url}/v1/chat",
                json={"messages": input.conversation, "context": input.context},
            )
            resp.raise_for_status()
            data = resp.json()
            return AgentOutput(
                content=data.get("content", ""),
                tool_calls=data.get("tool_calls", []),
            )

    async def run_async(self, input: AgentInput) -> AgentOutput:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.server_url}/v1/chat",
                json={"messages": input.conversation, "context": input.context},
            )
            resp.raise_for_status()
            data = resp.json()
            return AgentOutput(
                content=data.get("content", ""),
                tool_calls=data.get("tool_calls", []),
            )

    def stream(self, input: AgentInput) -> Iterator[str]:
        result = self.run(input)
        yield result.content

    def reset(self) -> None:
        pass

    def health_check(self) -> bool:
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{self.server_url}/health")
                return resp.status_code == 200
        except Exception:
            return False
