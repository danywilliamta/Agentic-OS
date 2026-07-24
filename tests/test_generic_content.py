"""Unit tests for agent_harness.tools.generic_content.generic_content_generator."""

import sys
from types import SimpleNamespace

from agent_harness.tools import generic_content


class FakeAnthropicMessages:
    def __init__(self, raise_error=None):
        self.raise_error = raise_error
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if self.raise_error:
            raise self.raise_error
        return SimpleNamespace(
            content=[SimpleNamespace(text="generated text")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=20),
        )


class TestGenericContentGenerator:
    def test_anthropic_success_returns_content_and_usage(self, monkeypatch):
        messages = FakeAnthropicMessages()
        fake_client = SimpleNamespace(messages=messages)
        monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

        result = generic_content.generic_content_generator(
            llm_provider="anthropic",
            api_key="k",
            model="claude-x",
            prompt="hello",
            system_prompt="be nice",
        )

        assert result == {
            "success": True,
            "content": "generated text",
            "usage": {"input_tokens": 10, "output_tokens": 20},
            "error": None,
        }
        assert messages.last_kwargs["system"] == "be nice"

    def test_unsupported_provider_returns_clear_error(self):
        result = generic_content.generic_content_generator(
            llm_provider="cohere", api_key="k", model="m", prompt="hi"
        )

        assert result == {
            "success": False,
            "content": None,
            "error": "Unsupported LLM provider: cohere",
        }

    def test_provider_error_is_caught(self, monkeypatch):
        messages = FakeAnthropicMessages(raise_error=RuntimeError("rate limited"))
        fake_client = SimpleNamespace(messages=messages)
        monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

        result = generic_content.generic_content_generator(
            llm_provider="anthropic", api_key="k", model="claude-x", prompt="hi"
        )

        assert result["success"] is False
        assert result["content"] is None
        assert "rate limited" in result["error"]

    def test_openai_success_maps_usage_field_names(self, monkeypatch):
        # OpenAI's usage object uses prompt_tokens/completion_tokens, unlike
        # Anthropic's input_tokens/output_tokens — pin down that the tool
        # normalizes both to the same {input_tokens, output_tokens} shape.
        fake_completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="openai reply"))],
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=7),
        )
        fake_completions = SimpleNamespace(create=lambda **kwargs: fake_completion)
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))
        fake_openai_module = SimpleNamespace(OpenAI=lambda api_key: fake_client)
        monkeypatch.setitem(sys.modules, "openai", fake_openai_module)

        result = generic_content.generic_content_generator(
            llm_provider="openai", api_key="k", model="gpt-x", prompt="hi"
        )

        assert result == {
            "success": True,
            "content": "openai reply",
            "usage": {"input_tokens": 5, "output_tokens": 7},
            "error": None,
        }

    def test_missing_optional_provider_dependency_is_handled_gracefully(self, monkeypatch):
        # Force the lazy `from openai import OpenAI` to fail regardless of
        # whether the optional `openai` package happens to be installed —
        # this pins down that a missing provider SDK degrades to an error
        # dict instead of crashing the whole agent.
        monkeypatch.setitem(sys.modules, "openai", None)

        result = generic_content.generic_content_generator(
            llm_provider="openai", api_key="k", model="gpt-x", prompt="hi"
        )

        assert result["success"] is False
        assert result["content"] is None
        assert "openai" in result["error"]
