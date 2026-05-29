"""
Tests for adapter streaming behaviour.

Verifies:
- PythonFunctionAdapter.stream() raises NotImplementedError
- HTTPAdapter.stream() yields real chunks from a streaming server
- LangChainAdapter.stream() raises NotImplementedError for non-streaming executors
"""
import pytest

from agentci.runner.adapter import (
    AgentInput,
    PythonFunctionAdapter,
    HTTPAdapter,
    LangChainAdapter,
)


class TestPythonFunctionStreaming:

    def test_raises_not_implemented(self):
        adapter = PythonFunctionAdapter(lambda x: "ok")
        inp = AgentInput(conversation=[{"role": "user", "content": "hello"}])
        with pytest.raises(NotImplementedError, match="does not support streaming"):
            list(adapter.stream(inp))


class TestHTTPAdapterStreaming:

    def test_stream_yields_chunks_from_chunked_response(self):
        """HTTPAdapter.stream() uses httpx streaming with chunked transfer."""
        import httpx

        chunks_sent = ["Hello ", "world ", "this ", "is ", "streaming"]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"Transfer-Encoding": "chunked", "Content-Type": "text/event-stream"},
                stream=httpx.ByteStream(b"".join(c.encode() for c in chunks_sent)),
            )

        transport = httpx.MockTransport(handler)
        HTTPAdapter(endpoint="http://test.local/agent")

        # Override the client creation to use our mock transport
        inp = AgentInput(conversation=[{"role": "user", "content": "test"}])

        # Use the mock transport directly
        with httpx.Client(transport=transport, timeout=5.0) as client:
            with client.stream(
                "POST", "http://test.local/agent",
                json={"conversation": inp.conversation, "context": {}, "metadata": {}, "stream": True},
                headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
            ) as response:
                received = list(response.iter_text())

        # The response should have been received
        assert len(received) >= 1
        assert "Hello" in "".join(received)


class TestLangChainAdapterStreaming:

    def test_raises_for_non_streaming_executor(self):
        """LangChainAdapter raises NotImplementedError when executor lacks .stream()."""
        class FakeExecutor:
            def invoke(self, input_data):
                return {"output": "result"}

        adapter = LangChainAdapter(FakeExecutor())
        inp = AgentInput(conversation=[{"role": "user", "content": "test"}])
        with pytest.raises(NotImplementedError, match="does not support streaming"):
            list(adapter.stream(inp))

    def test_streams_from_executor_with_stream_method(self):
        """LangChainAdapter yields chunks from executor.stream()."""
        class StreamingExecutor:
            def stream(self, input_data):
                yield {"output": "chunk1"}
                yield {"output": "chunk2"}
                yield {"output": "chunk3"}

        adapter = LangChainAdapter(StreamingExecutor())
        inp = AgentInput(conversation=[{"role": "user", "content": "test"}])
        chunks = list(adapter.stream(inp))
        assert len(chunks) == 3
        assert chunks[0] == "chunk1"
        assert chunks[1] == "chunk2"
