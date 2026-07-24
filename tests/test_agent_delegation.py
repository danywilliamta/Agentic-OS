"""Unit tests for agent_harness.tools.agent_delegation.agent_delegation."""

import pytest

from agent_harness.agent_factory import agent_factory
from agent_harness.tools.agent_delegation import agent_delegation


class FakeTargetAgent:
    def __init__(self, response="ok", tool_calls=None, metadata=None, raise_error=None):
        self._response = response
        self._tool_calls = tool_calls or []
        self._metadata = metadata or {}
        self._raise_error = raise_error
        self.invoke_calls = []

    async def invoke(self, user_id, message, context=None):
        self.invoke_calls.append({"user_id": user_id, "message": message, "context": context})
        if self._raise_error:
            raise self._raise_error
        return {"response": self._response, "tool_calls": self._tool_calls, "metadata": self._metadata}


class TestAgentDelegation:
    @pytest.mark.asyncio
    async def test_target_not_in_allowed_agents_short_circuits(self, monkeypatch):
        called = False

        def fake_get_agent(agent_id):
            nonlocal called
            called = True

        monkeypatch.setattr(agent_factory, "get_agent", fake_get_agent)

        result = await agent_delegation(
            target_agent_id="rogue-agent",
            task_description="do something",
            allowed_agents=["billing-agent", "support-agent"],
        )

        assert result["success"] is False
        assert "not in allowed agents" in result["error"]
        assert called is False  # never even looked the agent up

    @pytest.mark.asyncio
    async def test_target_agent_not_found(self, monkeypatch):
        monkeypatch.setattr(agent_factory, "get_agent", lambda agent_id: None)

        result = await agent_delegation(target_agent_id="ghost-agent", task_description="do something")

        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_success_forwards_response_tool_calls_and_metadata(self, monkeypatch):
        target = FakeTargetAgent(response="done!", tool_calls=[{"name": "x"}], metadata={"model": "claude"})
        monkeypatch.setattr(agent_factory, "get_agent", lambda agent_id: target)

        result = await agent_delegation(
            target_agent_id="billing-agent", task_description="check invoice", user_id="user-1"
        )

        assert result == {
            "success": True,
            "agent": "billing-agent",
            "result": "done!",
            "tool_calls": [{"name": "x"}],
            "metadata": {"model": "claude"},
        }
        assert target.invoke_calls[0]["user_id"] == "user-1"

    @pytest.mark.asyncio
    async def test_user_id_falls_back_to_context_user_id_when_absent(self, monkeypatch):
        target = FakeTargetAgent()
        monkeypatch.setattr(agent_factory, "get_agent", lambda agent_id: target)

        await agent_delegation(
            target_agent_id="billing-agent",
            task_description="task",
            context={"user_id": "ctx-user"},
        )

        assert target.invoke_calls[0]["user_id"] == "ctx-user"

    @pytest.mark.asyncio
    async def test_user_id_defaults_to_ephemeral_id_when_fully_absent(self, monkeypatch):
        target = FakeTargetAgent()
        monkeypatch.setattr(agent_factory, "get_agent", lambda agent_id: target)

        await agent_delegation(target_agent_id="billing-agent", task_description="task")

        assert target.invoke_calls[0]["user_id"].startswith("ephemeral-")

    @pytest.mark.asyncio
    async def test_exception_from_target_agent_is_caught(self, monkeypatch):
        target = FakeTargetAgent(raise_error=RuntimeError("target crashed"))
        monkeypatch.setattr(agent_factory, "get_agent", lambda agent_id: target)

        result = await agent_delegation(target_agent_id="billing-agent", task_description="task")

        assert result["success"] is False
        assert "target crashed" in result["error"]
        assert result["result"] is None
