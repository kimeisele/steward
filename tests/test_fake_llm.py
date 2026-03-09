"""Tests for FakeLLM — battle-hardened test infrastructure.

The FakeLLM is the foundation all engine/agent tests stand on.
If this fake is wrong, every test that uses it is suspect.
"""

from tests.conftest import FakeLLM, FakeResponse, FakeUsage


class TestFakeUsage:
    """FakeUsage models LLM token tracking."""

    def test_defaults(self):
        u = FakeUsage()
        assert u.input_tokens == 10
        assert u.output_tokens == 20

    def test_custom_values(self):
        u = FakeUsage(input_tokens=500, output_tokens=100)
        assert u.input_tokens == 500
        assert u.output_tokens == 100

    def test_zero_tokens(self):
        u = FakeUsage(input_tokens=0, output_tokens=0)
        assert u.input_tokens == 0
        assert u.output_tokens == 0


class TestFakeResponse:
    """FakeResponse models LLM API responses."""

    def test_defaults(self):
        r = FakeResponse()
        assert r.content == ""
        assert r.tool_calls is None
        assert r.usage is not None
        assert r.usage.input_tokens == 10

    def test_auto_creates_usage(self):
        """Usage is auto-created if not provided."""
        r = FakeResponse(content="hello")
        assert r.usage is not None
        assert isinstance(r.usage, FakeUsage)

    def test_custom_usage_preserved(self):
        """Explicit usage is not overwritten."""
        u = FakeUsage(input_tokens=999, output_tokens=1)
        r = FakeResponse(content="x", usage=u)
        assert r.usage.input_tokens == 999

    def test_empty_content(self):
        r = FakeResponse(content="")
        assert r.content == ""

    def test_json_content(self):
        """Brain-in-a-jar: response is JSON."""
        r = FakeResponse(content='{"response": "done"}')
        assert '"response"' in r.content

    def test_tool_call_content(self):
        """Brain-in-a-jar: tool call is JSON."""
        r = FakeResponse(content='{"tool": "bash", "params": {"command": "ls"}}')
        assert '"tool"' in r.content


class TestFakeLLM:
    """FakeLLM — deterministic, never calls real APIs."""

    def test_default_single_response(self):
        """Default FakeLLM returns "ok"."""
        llm = FakeLLM()
        resp = llm.invoke(messages=[])
        assert resp.content == "ok"

    def test_custom_responses_in_order(self):
        """Responses are returned in sequence."""
        llm = FakeLLM([
            FakeResponse(content="first"),
            FakeResponse(content="second"),
            FakeResponse(content="third"),
        ])
        assert llm.invoke(messages=[]).content == "first"
        assert llm.invoke(messages=[]).content == "second"
        assert llm.invoke(messages=[]).content == "third"

    def test_exhausted_returns_sentinel(self):
        """After all responses consumed, returns sentinel."""
        llm = FakeLLM([FakeResponse(content="only")])
        llm.invoke(messages=[])
        resp = llm.invoke(messages=[])
        assert resp.content == "[no more responses]"

    def test_tracks_call_count(self):
        llm = FakeLLM()
        assert llm.call_count == 0
        llm.invoke(messages=[])
        assert llm.call_count == 1
        llm.invoke(messages=[])
        assert llm.call_count == 2

    def test_records_call_kwargs(self):
        """Every invoke() call records its kwargs."""
        llm = FakeLLM()
        llm.invoke(messages=[{"role": "user", "content": "hi"}], max_tokens=512)
        assert len(llm.calls) == 1
        assert llm.calls[0]["max_tokens"] == 512

    def test_last_call_shortcut(self):
        """last_call returns the most recent invoke kwargs."""
        llm = FakeLLM([FakeResponse(content="a"), FakeResponse(content="b")])
        llm.invoke(messages=[], max_tokens=256)
        llm.invoke(messages=[], max_tokens=512)
        assert llm.last_call["max_tokens"] == 512

    def test_last_call_none_before_any_call(self):
        llm = FakeLLM()
        assert llm.last_call is None

    def test_usage_passthrough(self):
        """Usage from FakeResponse is accessible on the returned object."""
        u = FakeUsage(input_tokens=100, output_tokens=50)
        llm = FakeLLM([FakeResponse(content="x", usage=u)])
        resp = llm.invoke(messages=[])
        assert resp.usage.input_tokens == 100
        assert resp.usage.output_tokens == 50

    def test_reset(self):
        """reset() clears call history and restarts response sequence."""
        llm = FakeLLM([FakeResponse(content="a"), FakeResponse(content="b")])
        llm.invoke(messages=[])
        llm.invoke(messages=[])
        llm.reset()
        assert llm.call_count == 0
        assert llm.calls == []
        assert llm.invoke(messages=[]).content == "a"


class TestFakeLLMStreaming:
    """FakeLLM streaming support (invoke_stream)."""

    def test_has_invoke_stream(self):
        """FakeLLM supports invoke_stream for engine compatibility."""
        llm = FakeLLM()
        assert hasattr(llm, "invoke_stream")

    def test_stream_yields_text_deltas(self):
        """invoke_stream yields text_delta events, then done with response."""
        llm = FakeLLM([FakeResponse(content="hello world")])
        events = list(llm.invoke_stream(messages=[]))
        # At least one text_delta + one done
        types = [e.type for e in events]
        assert "text_delta" in types
        assert "done" in types

    def test_stream_done_has_response(self):
        """The done event carries the full FakeResponse."""
        llm = FakeLLM([FakeResponse(content="result")])
        events = list(llm.invoke_stream(messages=[]))
        done_event = [e for e in events if e.type == "done"][0]
        assert done_event.response.content == "result"

    def test_stream_tracks_calls(self):
        """invoke_stream records kwargs like invoke."""
        llm = FakeLLM()
        list(llm.invoke_stream(messages=[], max_tokens=768))
        assert llm.call_count == 1
        assert llm.last_call["max_tokens"] == 768

    def test_stream_json_mode(self):
        """JSON content streams as a single delta (not split mid-JSON)."""
        llm = FakeLLM([FakeResponse(content='{"response": "done"}')])
        events = list(llm.invoke_stream(messages=[]))
        deltas = [e for e in events if e.type == "text_delta"]
        assembled = "".join(e.text for e in deltas)
        assert assembled == '{"response": "done"}'


class TestFakeLLMEdgeCases:
    """Edge cases that engine.py might hit."""

    def test_none_usage(self):
        """Response with explicitly None usage (some providers do this)."""
        r = FakeResponse(content="x")
        r.usage = None  # type: ignore
        llm = FakeLLM([r])
        resp = llm.invoke(messages=[])
        assert resp.usage is None

    def test_empty_response_list(self):
        """Empty response list → immediate sentinel."""
        llm = FakeLLM([])
        resp = llm.invoke(messages=[])
        assert resp.content == "[no more responses]"

    def test_concurrent_safe(self):
        """Multiple sequential calls don't interfere."""
        llm = FakeLLM([
            FakeResponse(content="a"),
            FakeResponse(content="b"),
        ])
        r1 = llm.invoke(messages=[{"m": 1}])
        r2 = llm.invoke(messages=[{"m": 2}])
        assert r1.content == "a"
        assert r2.content == "b"
        assert llm.calls[0]["messages"] == [{"m": 1}]
        assert llm.calls[1]["messages"] == [{"m": 2}]

    def test_large_content(self):
        """Handles large response content without truncation."""
        big = "x" * 100_000
        llm = FakeLLM([FakeResponse(content=big)])
        resp = llm.invoke(messages=[])
        assert len(resp.content) == 100_000
