"""Unit tests for agent_harness.agent.Agent and its module-level helpers."""

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from langgraph.types import Command

from agent_harness.agent import Agent, _extract_text


# --------------------------------------------------------------------------
# Fake message / deep-agent doubles
#
# Agent only ever touches messages via hasattr()/getattr() (duck typing, no
# isinstance checks against langchain classes) — so plain objects exposing
# the same attributes are sufficient stand-ins and keep these tests free of
# any real model/graph dependency.
# --------------------------------------------------------------------------


class FakeAIMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = [] if content is None else content
        self.tool_calls = tool_calls or []
        self.type = "ai"


class FakeToolMessage:
    def __init__(self, content, tool_call_id, name="unknown"):
        self.content = content
        self.tool_call_id = tool_call_id
        self.name = name
        self.type = "tool"


class FakeHumanMessage:
    def __init__(self, content):
        self.content = content
        self.type = "human"


class FakeSnapshot:
    def __init__(self, values: Dict[str, Any]):
        self.values = values


class FakeCheckpointer:
    def __init__(self):
        self.deleted_threads: List[str] = []

    async def adelete_thread(self, thread_id: str) -> None:
        self.deleted_threads.append(thread_id)


class FakeDeepAgent:
    """Records calls and replays a queue of `ainvoke` results in order.

    Interrupt-resume tests need `ainvoke` to return a different result on
    each successive call within the same `invoke()`, so results are a queue
    rather than a single canned value.
    """

    def __init__(self, invoke_results: List[Dict[str, Any]], checkpointer=None, state: Optional[FakeSnapshot] = None):
        self._invoke_results = list(invoke_results)
        self.invoke_calls: List[Any] = []
        self.checkpointer = checkpointer
        self._state = state
        self.stream_events: List[Any] = []

    async def ainvoke(self, input_data, config):
        self.invoke_calls.append((input_data, config))
        return self._invoke_results.pop(0)

    async def aget_state(self, config):
        return self._state

    async def astream_events(self, input_data, config):
        for event in self.stream_events:
            yield event


def make_agent(deep_agent, agent_id="test-agent", config=None, tenant_id=None) -> Agent:
    return Agent(agent_id, deep_agent, config or {"model": {"name": "claude-x"}}, tenant_id=tenant_id)


class FakeTokenTracker:
    """Enough of TokenUsageTracker's surface for both call sites that touch
    it: `_log_token_usage` (async log_usage) and `_record_usage_metrics`
    (synchronous calculate_cost) — one double instead of two ad-hoc ones, no
    DB/network involved either way."""

    def __init__(self):
        self.logged_calls: List[Dict[str, Any]] = []
        self.calculate_cost_calls: List[Any] = []

    async def log_usage(self, **kwargs):
        self.logged_calls.append(kwargs)

    def calculate_cost(self, model, input_tokens, output_tokens):
        self.calculate_cost_calls.append((model, input_tokens, output_tokens))
        return {"input_cost": 0, "output_cost": 0, "total_cost": 0.0042}


# --------------------------------------------------------------------------
# _extract_text (module-level helper)
# --------------------------------------------------------------------------


class TestExtractText:
    def test_single_text_block(self):
        assert _extract_text([{"type": "text", "text": "hello"}]) == "hello"

    def test_thinking_then_text_block_only_keeps_text(self):
        content = [{"type": "thinking", "thinking": "hmm"}, {"type": "text", "text": "answer"}]
        assert _extract_text(content) == "answer"

    def test_tool_only_turn_with_no_text_block_returns_empty_string(self):
        content = [{"type": "tool_use", "id": "1", "name": "x", "input": {}}]
        assert _extract_text(content) == ""

    def test_plain_string_content_passthrough(self):
        assert _extract_text("plain text") == "plain text"

    def test_none_returns_empty_string(self):
        assert _extract_text(None) == ""

    def test_falsy_non_list_non_str_returns_empty_string(self):
        assert _extract_text(0) == ""
        assert _extract_text({}) == ""

    def test_truthy_non_list_non_str_falls_back_to_str_repr(self):
        assert _extract_text({"unexpected": "shape"}) == str({"unexpected": "shape"})


# --------------------------------------------------------------------------
# Agent.make_key / instance_key
# --------------------------------------------------------------------------


class TestMakeKey:
    def test_make_key_without_tenant(self):
        assert Agent.make_key("support-bot") == "support-bot"

    def test_make_key_with_tenant(self):
        assert Agent.make_key("support-bot", "tenant-42") == "support-bot:tenant-42"

    def test_instance_key_matches_make_key(self):
        agent = make_agent(FakeDeepAgent([]), agent_id="a", tenant_id="t")
        assert agent.instance_key == Agent.make_key("a", "t") == "a:t"

    def test_instance_key_single_tenant_deployment(self):
        agent = make_agent(FakeDeepAgent([]), agent_id="a")
        assert agent.instance_key == "a"


# --------------------------------------------------------------------------
# _format_todos
# --------------------------------------------------------------------------


class TestFormatTodos:
    def test_empty_todos_returns_empty_string(self):
        agent = make_agent(FakeDeepAgent([]))
        assert agent._format_todos([]) == ""

    def test_known_statuses_get_icons(self):
        agent = make_agent(FakeDeepAgent([]))
        out = agent._format_todos(
            [
                {"status": "pending", "content": "task a"},
                {"status": "in_progress", "content": "task b"},
                {"status": "completed", "content": "task c"},
            ]
        )
        assert "⏳" in out and "task a" in out
        assert "🔄" in out and "task b" in out
        assert "✅" in out and "task c" in out

    def test_unknown_status_gets_fallback_icon(self):
        agent = make_agent(FakeDeepAgent([]))
        out = agent._format_todos([{"status": "mystery", "content": "task"}])
        assert "❓" in out

    def test_missing_content_falls_back_to_placeholder(self):
        agent = make_agent(FakeDeepAgent([]))
        out = agent._format_todos([{"status": "pending"}])
        assert "Unknown task" in out


# --------------------------------------------------------------------------
# _format_tool_calls
# --------------------------------------------------------------------------


class TestFormatToolCalls:
    """Debug/log formatting only (source marks it "PRINTING TO DELETE") — a
    light smoke test per branch is enough, not exhaustive truncation coverage."""

    def test_empty_messages_returns_empty_string(self):
        agent = make_agent(FakeDeepAgent([]))
        assert agent._format_tool_calls([]) == ""

    def test_tool_call_args_are_shown_and_long_values_truncated(self):
        agent = make_agent(FakeDeepAgent([]))
        long_val = "x" * 150
        msg = FakeAIMessage(tool_calls=[{"name": "search", "args": {"q": long_val}}])
        out = agent._format_tool_calls([msg])
        assert "search" in out
        assert "..." in out and long_val not in out

    def test_thinking_block_is_shown(self):
        agent = make_agent(FakeDeepAgent([]))
        msg = FakeAIMessage(content=[{"type": "thinking", "thinking": "short thought"}])
        out = agent._format_tool_calls([msg])
        assert "Agent Thinking" in out
        assert "short thought" in out

    def test_tool_result_json_dict_is_pretty_printed(self):
        agent = make_agent(FakeDeepAgent([]))
        msg = FakeToolMessage(content='{"success": true, "count": 3}', tool_call_id="1")
        out = agent._format_tool_calls([msg])
        assert "success: True" in out
        assert "count: 3" in out

    def test_tool_result_non_json_string_is_shown_as_is(self):
        agent = make_agent(FakeDeepAgent([]))
        msg = FakeToolMessage(content="plain result", tool_call_id="1")
        out = agent._format_tool_calls([msg])
        assert "plain result" in out


# --------------------------------------------------------------------------
# _extract_tool_calls
# --------------------------------------------------------------------------


class TestExtractToolCalls:
    def test_matches_call_to_result_by_id(self):
        agent = make_agent(FakeDeepAgent([]))
        ai_msg = FakeAIMessage(tool_calls=[{"id": "1", "name": "search", "args": {"q": "x"}}])
        tool_msg = FakeToolMessage(content="found it", tool_call_id="1")

        result = agent._extract_tool_calls([ai_msg, tool_msg])

        assert result == [{"name": "search", "args": {"q": "x"}, "result": "found it"}]

    def test_unmatched_call_keeps_result_none(self):
        agent = make_agent(FakeDeepAgent([]))
        ai_msg = FakeAIMessage(tool_calls=[{"id": "1", "name": "search", "args": {}}])

        result = agent._extract_tool_calls([ai_msg])

        assert result == [{"name": "search", "args": {}, "result": None}]

    def test_order_is_preserved_across_multiple_calls(self):
        agent = make_agent(FakeDeepAgent([]))
        ai_msg = FakeAIMessage(
            tool_calls=[
                {"id": "1", "name": "first", "args": {}},
                {"id": "2", "name": "second", "args": {}},
            ]
        )
        result = agent._extract_tool_calls([ai_msg])
        assert [r["name"] for r in result] == ["first", "second"]

    def test_no_tool_calls_returns_empty_list(self):
        agent = make_agent(FakeDeepAgent([]))
        assert agent._extract_tool_calls([FakeHumanMessage("hi")]) == []


# --------------------------------------------------------------------------
# _extract_usage — shared by invoke() (_process_agent_response) and
# stream_invoke(), both need the exact same usage_metadata/response_metadata
# extraction from the last message of a run.
# --------------------------------------------------------------------------


class FakeUsageMessage:
    """Bare stand-in exposing only what _extract_usage touches — no content/
    tool_calls/type needed, unlike FakeAIMessage above."""

    def __init__(self, usage_metadata=None, response_metadata=None):
        if usage_metadata is not None:
            self.usage_metadata = usage_metadata
        if response_metadata is not None:
            self.response_metadata = response_metadata


class TestExtractUsage:
    def test_prefers_usage_metadata_over_response_metadata(self):
        agent = make_agent(FakeDeepAgent([]))
        msg = FakeUsageMessage(
            usage_metadata={"input_tokens": 10, "output_tokens": 5},
            response_metadata={"usage": {"input_tokens": 999, "output_tokens": 999}},
        )
        assert agent._extract_usage([msg]) == {"input_tokens": 10, "output_tokens": 5}

    def test_falls_back_to_response_metadata_usage(self):
        agent = make_agent(FakeDeepAgent([]))
        msg = FakeUsageMessage(response_metadata={"usage": {"input_tokens": 7, "output_tokens": 3}})
        assert agent._extract_usage([msg]) == {"input_tokens": 7, "output_tokens": 3}

    def test_ignores_falsy_usage_metadata(self):
        """An empty dict on usage_metadata (falsy) must not shadow a real
        response_metadata.usage — mirrors the `and last_msg.usage_metadata` guard."""
        agent = make_agent(FakeDeepAgent([]))
        msg = FakeUsageMessage(usage_metadata={}, response_metadata={"usage": {"input_tokens": 1, "output_tokens": 1}})
        assert agent._extract_usage([msg]) == {"input_tokens": 1, "output_tokens": 1}

    def test_response_metadata_without_usage_key_yields_none(self):
        agent = make_agent(FakeDeepAgent([]))
        msg = FakeUsageMessage(response_metadata={"other": "stuff"})
        assert agent._extract_usage([msg]) is None

    def test_response_metadata_not_a_dict_yields_none(self):
        agent = make_agent(FakeDeepAgent([]))
        msg = FakeUsageMessage(response_metadata="not-a-dict")
        assert agent._extract_usage([msg]) is None

    def test_message_without_usage_attributes_yields_none(self):
        agent = make_agent(FakeDeepAgent([]))
        assert agent._extract_usage([FakeHumanMessage("hi")]) is None

    def test_empty_messages_falls_back_to_result_usage(self):
        agent = make_agent(FakeDeepAgent([]))
        result = {"usage": {"input_tokens": 4, "output_tokens": 2}}
        assert agent._extract_usage([], result) == {"input_tokens": 4, "output_tokens": 2}

    def test_empty_messages_and_no_result_yields_none(self):
        agent = make_agent(FakeDeepAgent([]))
        assert agent._extract_usage([]) is None

    def test_uses_last_message_only(self):
        agent = make_agent(FakeDeepAgent([]))
        first = FakeUsageMessage(usage_metadata={"input_tokens": 1, "output_tokens": 1})
        last = FakeUsageMessage(usage_metadata={"input_tokens": 2, "output_tokens": 2})
        assert agent._extract_usage([first, last]) == {"input_tokens": 2, "output_tokens": 2}


# --------------------------------------------------------------------------
# _record_usage_metrics — Prometheus token/cost metrics, no-op unless metrics
# are enabled, a token tracker is configured, and usage was actually found.
# --------------------------------------------------------------------------


class TestRecordUsageMetrics:
    def test_noop_when_metrics_disabled(self, monkeypatch):
        monkeypatch.setattr("agent_harness.agent.METRICS_ENABLED", False)
        recorded = []
        monkeypatch.setattr("agent_harness.agent.record_token_usage", lambda *a, **k: recorded.append((a, k)))

        tracker = FakeTokenTracker()
        agent = Agent("bot", FakeDeepAgent([]), {"model": {"name": "claude-x"}}, token_tracker=tracker)

        agent._record_usage_metrics({"input_tokens": 10, "output_tokens": 5})

        assert recorded == []
        assert tracker.calculate_cost_calls == []

    def test_noop_when_usage_is_none(self, monkeypatch):
        monkeypatch.setattr("agent_harness.agent.METRICS_ENABLED", True)
        recorded = []
        monkeypatch.setattr("agent_harness.agent.record_token_usage", lambda *a, **k: recorded.append((a, k)))

        tracker = FakeTokenTracker()
        agent = Agent("bot", FakeDeepAgent([]), {"model": {"name": "claude-x"}}, token_tracker=tracker)

        agent._record_usage_metrics(None)

        assert recorded == []

    def test_noop_when_no_token_tracker(self, monkeypatch):
        monkeypatch.setattr("agent_harness.agent.METRICS_ENABLED", True)
        recorded = []
        monkeypatch.setattr("agent_harness.agent.record_token_usage", lambda *a, **k: recorded.append((a, k)))

        agent = Agent("bot", FakeDeepAgent([]), {"model": {"name": "claude-x"}}, token_tracker=None)

        agent._record_usage_metrics({"input_tokens": 10, "output_tokens": 5})

        assert recorded == []

    def test_records_cost_and_tokens_for_anthropic_format(self, monkeypatch):
        monkeypatch.setattr("agent_harness.agent.METRICS_ENABLED", True)
        recorded = []
        monkeypatch.setattr(
            "agent_harness.agent.record_token_usage",
            lambda agent_id, tenant_id, model, input_tokens, output_tokens, cost: recorded.append(
                (agent_id, tenant_id, model, input_tokens, output_tokens, cost)
            ),
        )

        tracker = FakeTokenTracker()
        agent = Agent(
            "bot", FakeDeepAgent([]), {"model": {"name": "claude-x"}}, tenant_id="t1", token_tracker=tracker
        )

        agent._record_usage_metrics({"input_tokens": 10, "output_tokens": 5})

        assert tracker.calculate_cost_calls == [("claude-x", 10, 5)]
        assert recorded == [("bot", "t1", "claude-x", 10, 5, 0.0042)]

    def test_falls_back_to_openai_token_field_names(self, monkeypatch):
        monkeypatch.setattr("agent_harness.agent.METRICS_ENABLED", True)
        recorded = []
        monkeypatch.setattr(
            "agent_harness.agent.record_token_usage",
            lambda agent_id, tenant_id, model, input_tokens, output_tokens, cost: recorded.append(
                (input_tokens, output_tokens)
            ),
        )

        tracker = FakeTokenTracker()
        agent = Agent("bot", FakeDeepAgent([]), {"model": {"name": "gpt-4"}}, token_tracker=tracker)

        agent._record_usage_metrics({"prompt_tokens": 8, "completion_tokens": 4})

        assert recorded == [(8, 4)]


# --------------------------------------------------------------------------
# invoke() — nominal + interrupt flows
# --------------------------------------------------------------------------


class TestInvoke:
    @pytest.mark.asyncio
    async def test_nominal_invoke_returns_expected_shape(self):
        final = {
            "messages": [FakeAIMessage(content=[{"type": "text", "text": "Hello there"}])],
            "usage": {"total_tokens": 42},
        }
        deep_agent = FakeDeepAgent([final])
        agent = make_agent(deep_agent, agent_id="bot", config={"model": {"name": "claude-x"}}, tenant_id="t1")

        result = await agent.invoke(user_id="u1", message="hi")

        assert result["agent_id"] == "bot"
        assert result["tenant_id"] == "t1"
        assert result["thread_id"] == "bot:t1-u1"
        assert result["response"] == "Hello there"
        assert result["tool_calls"] == []
        assert result["metadata"] == {"model": "claude-x", "usage": {"total_tokens": 42}}

    @pytest.mark.asyncio
    async def test_invoke_builds_message_with_context_metadata(self):
        final = {"messages": [FakeAIMessage(content=[{"type": "text", "text": "ok"}])]}
        deep_agent = FakeDeepAgent([final])
        agent = make_agent(deep_agent)

        await agent.invoke(user_id="u1", message="hi", context={"foo": "bar"})

        input_data, _config = deep_agent.invoke_calls[0]
        assert input_data["messages"][0]["metadata"] == {"foo": "bar"}

    @pytest.mark.asyncio
    async def test_invoke_extracts_tool_calls_from_final_result(self):
        ai_msg = FakeAIMessage(
            content=[{"type": "text", "text": "done"}],
            tool_calls=[{"id": "1", "name": "search", "args": {"q": "x"}}],
        )
        tool_msg = FakeToolMessage(content="results", tool_call_id="1")
        final = {"messages": [ai_msg, tool_msg]}
        agent = make_agent(FakeDeepAgent([final]))

        result = await agent.invoke(user_id="u1", message="search for x")

        assert result["tool_calls"] == [{"name": "search", "args": {"q": "x"}, "result": "results"}]

    @pytest.mark.asyncio
    async def test_invoke_handles_dict_style_last_message(self):
        final = {"messages": [{"content": "raw dict content"}]}
        agent = make_agent(FakeDeepAgent([final]))

        result = await agent.invoke(user_id="u1", message="hi")

        assert result["response"] == "raw dict content"

    @pytest.mark.asyncio
    async def test_interrupt_approved_resumes_and_returns_final_response(self, monkeypatch):
        interrupt_obj = SimpleNamespace(
            value={"action_requests": [{"name": "risky_tool", "args": {"x": 1}}]}
        )
        interrupted_result = {
            "messages": [FakeAIMessage()],
            "__interrupt__": [interrupt_obj],
        }
        final_result = {"messages": [FakeAIMessage(content=[{"type": "text", "text": "approved and done"}])]}

        deep_agent = FakeDeepAgent([interrupted_result, final_result])
        agent = make_agent(deep_agent)

        monkeypatch.setattr("builtins.input", lambda prompt="": "y")

        result = await agent.invoke(user_id="u1", message="do the risky thing")

        assert result["response"] == "approved and done"
        assert len(deep_agent.invoke_calls) == 2
        resume_input, _ = deep_agent.invoke_calls[1]
        assert isinstance(resume_input, Command)
        assert resume_input.resume == {"decisions": [{"type": "approve"}]}

    @pytest.mark.asyncio
    async def test_interrupt_rejected_resumes_with_reject_decision(self, monkeypatch):
        interrupt_obj = SimpleNamespace(value={"action_requests": [{"name": "risky_tool", "args": {}}]})
        interrupted_result = {"messages": [FakeAIMessage()], "__interrupt__": [interrupt_obj]}
        final_result = {"messages": [FakeAIMessage(content=[{"type": "text", "text": "rejected"}])]}

        deep_agent = FakeDeepAgent([interrupted_result, final_result])
        agent = make_agent(deep_agent)
        monkeypatch.setattr("builtins.input", lambda prompt="": "n")

        result = await agent.invoke(user_id="u1", message="do the risky thing")

        assert result["response"] == "rejected"
        resume_input, _ = deep_agent.invoke_calls[1]
        assert resume_input.resume == {"decisions": [{"type": "reject"}]}

    @pytest.mark.asyncio
    async def test_interrupt_eof_during_input_rejects_all_by_default(self, monkeypatch):
        interrupt_obj = SimpleNamespace(
            value={"action_requests": [{"name": "a", "args": {}}, {"name": "b", "args": {}}]}
        )
        interrupted_result = {"messages": [FakeAIMessage()], "__interrupt__": [interrupt_obj]}
        final_result = {"messages": [FakeAIMessage(content=[{"type": "text", "text": "auto-rejected"}])]}

        deep_agent = FakeDeepAgent([interrupted_result, final_result])
        agent = make_agent(deep_agent)

        def raise_eof(prompt=""):
            raise EOFError()

        monkeypatch.setattr("builtins.input", raise_eof)

        result = await agent.invoke(user_id="u1", message="do risky things")

        assert result["response"] == "auto-rejected"
        resume_input, _ = deep_agent.invoke_calls[1]
        assert resume_input.resume == {"decisions": [{"type": "reject"}, {"type": "reject"}]}


# --------------------------------------------------------------------------
# stream_invoke()
# --------------------------------------------------------------------------


class TestStreamInvoke:
    @pytest.mark.asyncio
    async def test_yields_all_events_and_reads_final_state(self):
        deep_agent = FakeDeepAgent(
            [], state=FakeSnapshot({"messages": [FakeAIMessage()], "todos": []})
        )
        deep_agent.stream_events = [{"event": "on_chat_model_start"}, {"event": "on_chat_model_end"}]
        agent = make_agent(deep_agent)

        events = [e async for e in agent.stream_invoke(user_id="u1", message="hi")]

        assert events == deep_agent.stream_events

    @pytest.mark.asyncio
    async def test_logs_token_usage_after_streaming_when_usage_present(self):
        """Regression: astream_events never surfaces usage itself — before
        _extract_usage/_record_usage_metrics were wired into stream_invoke, a
        chat driven purely through SSE never logged anything to token_tracker,
        unlike invoke()."""
        final_msg = FakeAIMessage(content=[{"type": "text", "text": "done"}])
        final_msg.usage_metadata = {"input_tokens": 12, "output_tokens": 6}

        deep_agent = FakeDeepAgent([], state=FakeSnapshot({"messages": [final_msg], "todos": []}))
        deep_agent.stream_events = [{"event": "on_chat_model_end"}]

        tracker = FakeTokenTracker()
        agent = Agent("bot", deep_agent, {"model": {"name": "claude-x"}}, token_tracker=tracker)

        async for _ in agent.stream_invoke(user_id="u1", message="hi"):
            pass

        assert len(tracker.logged_calls) == 1
        assert tracker.logged_calls[0]["input_tokens"] == 12
        assert tracker.logged_calls[0]["output_tokens"] == 6

    @pytest.mark.asyncio
    async def test_does_not_log_when_final_message_has_no_usage(self):
        deep_agent = FakeDeepAgent([], state=FakeSnapshot({"messages": [FakeAIMessage()], "todos": []}))
        deep_agent.stream_events = []

        tracker = FakeTokenTracker()
        agent = Agent("bot", deep_agent, {"model": {"name": "claude-x"}}, token_tracker=tracker)

        async for _ in agent.stream_invoke(user_id="u1", message="hi"):
            pass

        assert tracker.logged_calls == []


# --------------------------------------------------------------------------
# get_history()
# --------------------------------------------------------------------------


class TestGetHistory:
    @pytest.mark.asyncio
    async def test_returns_human_and_ai_turns_with_text(self):
        messages = [
            FakeHumanMessage("hi there"),
            FakeAIMessage(content=[{"type": "text", "text": "hello!"}]),
        ]
        deep_agent = FakeDeepAgent([], state=FakeSnapshot({"messages": messages}))
        agent = make_agent(deep_agent)

        history = await agent.get_history(user_id="u1")

        assert history == [
            {"role": "user", "content": "hi there"},
            {"role": "assistant", "content": "hello!"},
        ]

    @pytest.mark.asyncio
    async def test_tool_only_ai_turn_is_omitted(self):
        messages = [
            FakeHumanMessage("do something"),
            FakeAIMessage(content=[], tool_calls=[{"id": "1", "name": "x", "args": {}}]),
            FakeToolMessage(content="result", tool_call_id="1"),
            FakeAIMessage(content=[{"type": "text", "text": "done"}]),
        ]
        deep_agent = FakeDeepAgent([], state=FakeSnapshot({"messages": messages}))
        agent = make_agent(deep_agent)

        history = await agent.get_history(user_id="u1")

        assert history == [
            {"role": "user", "content": "do something"},
            {"role": "assistant", "content": "done"},
        ]

    @pytest.mark.asyncio
    async def test_no_messages_key_returns_empty_list(self):
        deep_agent = FakeDeepAgent([], state=FakeSnapshot({}))
        agent = make_agent(deep_agent)

        assert await agent.get_history(user_id="u1") == []


# --------------------------------------------------------------------------
# clear_history()
# --------------------------------------------------------------------------


class TestClearHistory:
    @pytest.mark.asyncio
    async def test_deletes_thread_via_checkpointer(self):
        checkpointer = FakeCheckpointer()
        deep_agent = FakeDeepAgent([], checkpointer=checkpointer)
        agent = make_agent(deep_agent, agent_id="bot", tenant_id="t1")

        await agent.clear_history(user_id="u1")

        assert checkpointer.deleted_threads == ["bot:t1-u1"]

    @pytest.mark.asyncio
    async def test_no_checkpointer_is_a_no_op(self):
        deep_agent = FakeDeepAgent([], checkpointer=None)
        agent = make_agent(deep_agent)

        # Should not raise even though there's nothing to delete against.
        await agent.clear_history(user_id="u1")


# --------------------------------------------------------------------------
# get_config() / get_tools()
# --------------------------------------------------------------------------


class TestConfigAccessors:
    def test_get_config_returns_full_config_dict(self):
        config = {"model": {"name": "x"}, "tools": []}
        agent = make_agent(FakeDeepAgent([]), config=config)
        assert agent.get_config() is config

    def test_get_tools_returns_configured_tool_names(self):
        config = {"tools": [{"name": "tool_a"}, {"name": "tool_b"}]}
        agent = make_agent(FakeDeepAgent([]), config=config)
        assert agent.get_tools() == ["tool_a", "tool_b"]


# --------------------------------------------------------------------------
# resume()
# --------------------------------------------------------------------------


class TestResume:
    @pytest.mark.asyncio
    async def test_resume_approve_sends_approve_decision(self):
        final = {"messages": [FakeAIMessage(content=[{"type": "text", "text": "resumed"}])]}
        deep_agent = FakeDeepAgent([final])
        agent = make_agent(deep_agent)

        result = await agent.resume(user_id="u1", approve=True)

        assert result["response"] == "resumed"
        input_data, _ = deep_agent.invoke_calls[0]
        assert input_data.resume == {"decisions": [{"type": "approve"}]}

    @pytest.mark.asyncio
    async def test_resume_reject_sends_reject_decision(self):
        final = {"messages": [FakeAIMessage(content=[{"type": "text", "text": "resumed"}])]}
        deep_agent = FakeDeepAgent([final])
        agent = make_agent(deep_agent)

        await agent.resume(user_id="u1", approve=False)

        input_data, _ = deep_agent.invoke_calls[0]
        assert input_data.resume == {"decisions": [{"type": "reject"}]}
