"""
Agent adapters for AgentCI.

Each adapter wraps a different type of agent (Python function, HTTP API,
LangChain executor, MCP server) behind a uniform interface.

Streaming contract:
  - stream() yields chunks as they arrive from the provider.
  - If the provider does not support streaming natively, stream()
    raises NotImplementedError. Callers must check and fall back to run().
  - No adapter fakes streaming by calling run() and yielding once.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterator

import httpx

logger = logging.getLogger(__name__)


@dataclass
class AgentInput:
    """Standardised input to any agent adapter."""
    conversation: list[dict[str, str]]
    context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentOutput:
    """Standardised output from any agent adapter."""
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class PythonFunctionAdapter:
    """
    Wraps a plain Python callable as an agent.

    The function must accept a dict with 'messages' and 'context' keys
    and return either a string or a dict with a 'response'/'content' key.
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
        """
        PythonFunctionAdapter does not support streaming.

        The underlying function is synchronous and returns a complete
        response. There is no way to stream partial results.
        """
        raise NotImplementedError(
            "PythonFunctionAdapter does not support streaming. "
            "The underlying function returns a complete response. "
            "Use run() instead."
        )

    def reset(self) -> None:
        """No state to reset for stateless function adapters."""
        pass

    def health_check(self) -> bool:
        return True


class HTTPAdapter:
    """
    Calls any agent via its REST API endpoint.

    Expects a POST endpoint that accepts JSON with conversation and context,
    and returns JSON with a 'content' field.

    Streaming uses httpx's streaming response to yield chunks as they
    arrive from the server (requires the server to support chunked
    transfer encoding or SSE).
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
        """
        Stream response chunks from the HTTP endpoint.

        Uses httpx streaming to yield bytes as they arrive.
        The server must support chunked transfer encoding.
        """
        with httpx.Client(timeout=self.timeout) as client:
            with client.stream(
                "POST",
                self.endpoint,
                headers={**self.headers, "Accept": "text/event-stream"},
                json={
                    "conversation": input.conversation,
                    "context": input.context,
                    "metadata": input.metadata,
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()
                for chunk in response.iter_text():
                    if chunk.strip():
                        yield chunk

    def reset(self) -> None:
        """HTTP adapters are stateless — nothing to reset."""
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
        """
        Stream from LangChain executor using its native stream method.

        Requires the executor to support .stream() (LangChain >= 0.1).
        Falls back to NotImplementedError if the executor doesn't support it.
        """
        if not hasattr(self._executor, "stream"):
            raise NotImplementedError(
                "This LangChain executor does not support streaming. "
                "Use run() instead, or upgrade to LangChain >= 0.1."
            )
        last_msg = input.conversation[-1]["content"] if input.conversation else ""
        for chunk in self._executor.stream({"input": last_msg}):
            if isinstance(chunk, dict):
                text = chunk.get("output", chunk.get("text", ""))
                if text:
                    yield text
            elif isinstance(chunk, str):
                yield chunk
            else:
                # LangChain RunLogPatch or AddableDict
                text = str(chunk)
                if text:
                    yield text

    def reset(self) -> None:
        """Reset executor memory if available."""
        if hasattr(self._executor, "memory") and self._executor.memory:
            self._executor.memory.clear()

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
        """
        Stream from MCP server using SSE.

        The MCP server must support the /v1/chat/stream endpoint
        with server-sent events.
        """
        with httpx.Client(timeout=self.timeout) as client:
            with client.stream(
                "POST",
                f"{self.server_url}/v1/chat/stream",
                json={"messages": input.conversation, "context": input.context},
                headers={"Accept": "text/event-stream"},
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            chunk = __import__("json").loads(data)
                            text = chunk.get("content", chunk.get("text", ""))
                            if text:
                                yield text
                        except __import__("json").JSONDecodeError:
                            yield data

    def reset(self) -> None:
        """MCP adapters are stateless — nothing to reset."""
        pass

    def health_check(self) -> bool:
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{self.server_url}/health")
                return resp.status_code == 200
        except Exception:
            return False
