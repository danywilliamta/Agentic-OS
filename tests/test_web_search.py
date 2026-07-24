"""Unit tests for agent_harness.tools.web_search.web_search."""

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
