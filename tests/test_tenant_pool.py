"""Unit tests for agent_harness.tenant_pool.TenantAgentPool."""

import pytest
import yaml

from agent_harness.agent import Agent
from agent_harness.agent_factory import agent_factory
from agent_harness.tenant_pool import TenantAgentPool, _DynamicContextMiddleware

SUPPORT_TEMPLATE = {
    "agent_id": "support",
    "display_name": "Support Agent",
    "system_prompt": "You help with support.",
    "tools": [
        {"type": "agent_delegation", "name": "delegate_to_agent", "config": {}},
        {
            "type": "some_tool",
            "name": "some_tool",
            "tenant_param": "workspace_id",
            "config": {"other": "value"},
        },
    ],
}
BILLING_TEMPLATE = {
    "agent_id": "billing",
    "display_name": "Billing Agent",
    "delegatable": False,
    "system_prompt": "You help with billing.",
    "tools": [],
}
INVENTORY_TEMPLATE = {
    "agent_id": "inventory",
    "display_name": "Inventory Agent",
    "system_prompt": "You track inventory.",
    "tools": [],
}


@pytest.fixture(autouse=True)
def clean_agents_cache():
    """`agent_factory` is a process-wide singleton — tests must not leak cache entries."""
    agent_factory.agents_cache.clear()
    yield
    agent_factory.agents_cache.clear()


@pytest.fixture
def configs_dir(tmp_path):
    for name, template in (
        ("support", SUPPORT_TEMPLATE),
        ("billing", BILLING_TEMPLATE),
        ("inventory", INVENTORY_TEMPLATE),
    ):
        (tmp_path / f"{name}.yml").write_text(yaml.safe_dump(template))
    return tmp_path


async def fake_context_provider(tenant_id, agent_type, display_name, static_instructions):
    return f"prompt for {display_name} ({tenant_id})"


@pytest.fixture
def pool(configs_dir):
    return TenantAgentPool(
        configs_dir=configs_dir,
        agent_types=["support", "billing", "inventory"],
        context_provider=fake_context_provider,
    )


class FakeAgent:
    def __init__(self, agent_id, tenant_id):
        self.agent_id = agent_id
        self.tenant_id = tenant_id
        self.instance_key = Agent.make_key(agent_id, tenant_id)


def install_fake_create_from_dict(monkeypatch, captured_calls=None):
    """Mimics AgentFactory.create_from_dict's caching side effect without
    touching create_deep_agent — records the config/middleware it was called
    with and registers a FakeAgent under the real agents_cache."""

    async def fake_create_from_dict(config, middleware=None, tenant_id=None):
        agent = FakeAgent(config["agent_id"], tenant_id)
        agent_factory.agents_cache[agent.instance_key] = agent
        if captured_calls is not None:
            captured_calls.append({"config": config, "middleware": middleware, "tenant_id": tenant_id})
        return agent

    monkeypatch.setattr(agent_factory, "create_from_dict", fake_create_from_dict)
    return fake_create_from_dict


# --------------------------------------------------------------------------
# _load_template
# --------------------------------------------------------------------------


class TestLoadTemplate:
    def test_loads_yaml_content(self, pool):
        assert pool._load_template("support") == SUPPORT_TEMPLATE

    def test_second_load_uses_cache_not_disk(self, pool, configs_dir):
        pool._load_template("support")
        (configs_dir / "support.yml").unlink()

        # If this weren't cached, the missing file would raise FileNotFoundError.
        assert pool._load_template("support") == SUPPORT_TEMPLATE


# --------------------------------------------------------------------------
# _render_tool_spec
# --------------------------------------------------------------------------


class TestRenderToolSpec:
    def test_agent_delegation_excludes_self_and_non_delegatable_siblings(self, pool):
        sibling_keys = {"support": "support:t1", "billing": "billing:t1", "inventory": "inventory:t1"}
        spec = {"type": "agent_delegation", "name": "delegate_to_agent", "config": {}}

        rendered = pool._render_tool_spec(spec, tenant_id="t1", agent_type="support", sibling_keys=sibling_keys)

        assert rendered["config"]["allowed_agents"] == ["inventory:t1"]
        assert "inventory:t1" in rendered["description"]
        assert "billing:t1" not in rendered["description"]
        assert "support:t1" not in rendered["description"]

    def test_tenant_param_curries_tenant_id_and_is_stripped_from_spec(self, pool):
        spec = {"type": "some_tool", "name": "some_tool", "tenant_param": "workspace_id", "config": {"other": "value"}}

        rendered = pool._render_tool_spec(spec, tenant_id="t1", agent_type="support", sibling_keys={})

        assert rendered["config"] == {"other": "value", "workspace_id": "t1"}
        assert "tenant_param" not in rendered

    def test_plain_tool_spec_is_copied_not_aliased(self, pool):
        spec = {"type": "generic_tool", "name": "x", "config": {"a": 1}}

        rendered = pool._render_tool_spec(spec, tenant_id="t1", agent_type="support", sibling_keys={})
        spec["config"]["a"] = 999  # mutate the original template dict afterwards

        assert rendered["config"] == {"a": 1}


# --------------------------------------------------------------------------
# _DynamicContextMiddleware
# --------------------------------------------------------------------------


class FakeModelRequest:
    def __init__(self):
        self.system_message = None

    def override(self, system_message):
        self.system_message = system_message
        return self


class TestDynamicContextMiddleware:
    @pytest.mark.asyncio
    async def test_rebuilds_system_prompt_from_context_provider_before_each_call(self):
        seen_args = []

        async def provider(tenant_id, agent_type, display_name, static_instructions):
            seen_args.append((tenant_id, agent_type, display_name, static_instructions))
            return "fresh prompt"

        middleware = _DynamicContextMiddleware("t1", "support", "Support Agent", "static instr", provider)
        request = FakeModelRequest()

        async def handler(req):
            return req.system_message.content

        result = await middleware.awrap_model_call(request, handler)

        assert seen_args == [("t1", "support", "Support Agent", "static instr")]
        assert result == "fresh prompt"


# --------------------------------------------------------------------------
# _build_agent
# --------------------------------------------------------------------------


class TestBuildAgent:
    @pytest.mark.asyncio
    async def test_wires_empty_static_prompt_rendered_tools_and_middleware(self, pool, monkeypatch):
        calls = []
        install_fake_create_from_dict(monkeypatch, calls)
        sibling_keys = {"support": "support:t1", "billing": "billing:t1", "inventory": "inventory:t1"}

        await pool._build_agent("t1", "support", sibling_keys)

        call = calls[0]
        assert call["config"]["system_prompt"] == ""  # injected per-call by the middleware instead
        assert call["tenant_id"] == "t1"
        assert len(call["middleware"]) == 1
        assert isinstance(call["middleware"][0], _DynamicContextMiddleware)

        delegation_tool = next(t for t in call["config"]["tools"] if t["type"] == "agent_delegation")
        assert delegation_tool["config"]["allowed_agents"] == ["inventory:t1"]


# --------------------------------------------------------------------------
# get_agent (+ LRU eviction)
# --------------------------------------------------------------------------


class TestGetAgent:
    @pytest.mark.asyncio
    async def test_unknown_agent_type_raises(self, pool):
        with pytest.raises(ValueError, match="Unknown agent_type"):
            await pool.get_agent("t1", "not-a-real-type")

    @pytest.mark.asyncio
    async def test_building_one_agent_type_builds_the_whole_tenant_family(self, pool, monkeypatch):
        install_fake_create_from_dict(monkeypatch)

        agent = await pool.get_agent("t1", "support")

        assert agent.agent_id == "support"
        assert agent_factory.get_agent(Agent.make_key("billing", "t1")) is not None
        assert agent_factory.get_agent(Agent.make_key("inventory", "t1")) is not None

    @pytest.mark.asyncio
    async def test_second_call_for_same_tenant_reuses_cache(self, pool, monkeypatch):
        calls = []
        install_fake_create_from_dict(monkeypatch, calls)

        await pool.get_agent("t1", "support")
        built_after_first_call = len(calls)
        await pool.get_agent("t1", "support")

        assert len(calls) == built_after_first_call

    @pytest.mark.asyncio
    async def test_lru_eviction_drops_oldest_tenants_whole_family(self, configs_dir, monkeypatch):
        install_fake_create_from_dict(monkeypatch)
        small_pool = TenantAgentPool(
            configs_dir=configs_dir,
            agent_types=["support", "billing", "inventory"],
            context_provider=fake_context_provider,
            max_cached_tenants=1,
        )

        await small_pool.get_agent("t1", "support")
        await small_pool.get_agent("t2", "support")  # exceeds capacity -> evicts t1's family

        assert agent_factory.get_agent(Agent.make_key("support", "t1")) is None
        assert agent_factory.get_agent(Agent.make_key("billing", "t1")) is None
        assert agent_factory.get_agent(Agent.make_key("support", "t2")) is not None
