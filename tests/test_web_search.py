"""Unit tests for agent_harness.tools.web_search.web_search."""

import asyncio
import time

import pytest

from agent_harness.tools.web_search import web_search


def make_fake_tavily_search(raw_results=None, raise_error=None):
    class FakeTavilySearch:
        def __init__(self, max_results, search_depth, api_key):
            self.max_results = max_results
            self.search_depth = search_depth
            self.api_key = api_key

        def invoke(self, args):
            if raise_error:
                raise raise_error
            return raw_results

    return FakeTavilySearch


class TestWebSearch:
    @pytest.mark.asyncio
    async def test_missing_api_key_returns_clear_error(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)

        result = await web_search(query="python testing")

        assert result["success"] is False
        assert result["results"] == []
        assert "TAVILY_API_KEY" in result["error"]

    @pytest.mark.asyncio
    async def test_success_formats_results_and_defaults_missing_fields(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")
        raw = {
            "results": [
                {"title": "Full", "url": "https://x", "content": "text", "score": 0.9},
                {"title": "Partial"},  # missing url/content/score -> should default
            ]
        }
        monkeypatch.setattr("langchain_tavily.TavilySearch", make_fake_tavily_search(raw_results=raw))

        result = await web_search(query="python testing")

        assert result["success"] is True
        assert result["query"] == "python testing"
        assert result["results"] == [
            {"title": "Full", "url": "https://x", "content": "text", "score": 0.9},
            {"title": "Partial", "url": "", "content": "", "score": 0.0},
        ]

    @pytest.mark.asyncio
    async def test_non_dict_raw_results_yields_empty_results(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")
        monkeypatch.setattr("langchain_tavily.TavilySearch", make_fake_tavily_search(raw_results=["unexpected"]))

        result = await web_search(query="python testing")

        assert result["success"] is True
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_search_exception_is_caught(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")
        monkeypatch.setattr(
            "langchain_tavily.TavilySearch", make_fake_tavily_search(raise_error=RuntimeError("tavily down"))
        )

        result = await web_search(query="python testing")

        assert result["success"] is False
        assert result["results"] == []
        assert "tavily down" in result["error"]

    @pytest.mark.asyncio
    async def test_invoke_runs_via_asyncio_to_thread(self, monkeypatch):
        """`TavilySearch.invoke()` is synchronous/network-blocking — calling it
        directly inside this async def would block the whole event loop (see
        test below for the observable effect). Pin down that it's actually
        routed through asyncio.to_thread rather than called inline."""
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")
        monkeypatch.setattr("langchain_tavily.TavilySearch", make_fake_tavily_search(raw_results={"results": []}))

        real_to_thread = asyncio.to_thread
        calls = []

        async def spying_to_thread(func, *args, **kwargs):
            calls.append((func, args, kwargs))
            return await real_to_thread(func, *args, **kwargs)

        monkeypatch.setattr("agent_harness.tools.web_search.asyncio.to_thread", spying_to_thread)

        result = await web_search(query="python testing")

        assert result["success"] is True
        assert len(calls) == 1
        func, args, kwargs = calls[0]
        assert func.__name__ == "invoke"
        assert args == ({"query": "python testing"},)
        assert kwargs == {}

    @pytest.mark.asyncio
    async def test_two_concurrent_searches_do_not_serialize_on_the_event_loop(self, monkeypatch):
        """Regression test for the actual bug: before routing through
        asyncio.to_thread, invoke() ran synchronously inline, so two
        "parallel" web_search calls (e.g. the model firing several tool calls
        in one turn) actually ran back-to-back instead of concurrently —
        visible in prod as a ~doubled wall-clock delay per extra call."""
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")

        class SlowFakeTavilySearch:
            def __init__(self, max_results, search_depth, api_key):
                pass

            def invoke(self, args):
                time.sleep(0.2)
                return {"results": []}

        monkeypatch.setattr("langchain_tavily.TavilySearch", SlowFakeTavilySearch)

        start = time.monotonic()
        results = await asyncio.gather(web_search(query="q1"), web_search(query="q2"))
        elapsed = time.monotonic() - start

        assert all(r["success"] for r in results)
        # Serialized (pre-fix) would take ~0.4s; running concurrently on
        # separate threads keeps it close to a single 0.2s sleep.
        assert elapsed < 0.35
