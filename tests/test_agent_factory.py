"""Unit tests for agent_harness.agent_factory.AgentFactory."""

import sys

import pytest
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from langgraph.checkpoint.memory import MemorySaver

from agent_harness.agent import Agent
from agent_harness.agent_factory import AgentFactory
from agent_harness.tool_registry import tool_registry

# `agent_harness/__init__.py` does `from agent_harness.agent_factory import
# ..., agent_factory`, which rebinds the `agent_factory` attribute on the
# `agent_harness` package to the singleton instance — shadowing the
# submodule of the same name. `import agent_harness.agent_factory as X`
# would silently pick up that instance instead of the module, so pull the
# real module straight out of sys.modules instead.
agent_factory_module = sys.modules["agent_harness.agent_factory"]


@pytest.fixture
def factory() -> AgentFactory:
    return AgentFactory()


@pytest.fixture
def registered_echo_tool():
    """Register a throwaway tool so `_configure_tools` has something real to resolve."""

    @tool_registry.register(name="echo_tool_for_tests", category="test")
    def echo(message: str) -> str:
        """Echo the given message back."""
        return message

    yield "echo_tool_for_tests"
    tool_registry.tools.pop("echo_tool_for_tests", None)


class FakePostgresCheckpointer:
    def __init__(self):
        self.setup_called = False

    async def setup(self):
        self.setup_called = True


class FakePostgresCtxMgr:
    def __init__(self, checkpointer):
        self._checkpointer = checkpointer

    async def __aenter__(self):
        return self._checkpointer

    async def __aexit__(self, *exc):
        return False


# --------------------------------------------------------------------------
# _configure_tools / env var resolution
# --------------------------------------------------------------------------


class TestConfigureTools:
    def test_builds_tool_resolves_env_var_and_overrides_description(
        self, factory, registered_echo_tool, monkeypatch
    ):
        monkeypatch.setenv("ECHO_VALUE", "resolved-from-env")
        tools_config = [
            {
                "type": registered_echo_tool,
                "name": "my_echo",
                "config": {"message": "${ECHO_VALUE}"},
                "description": "Custom description",
            }
        ]

        tools = factory._configure_tools(tools_config)

        assert len(tools) == 1
        configured = tools[0]
        assert configured.__name__ == "my_echo"
        assert configured.__doc__ == "Custom description"
        assert configured() == "resolved-from-env"

    def test_missing_env_var_leaves_placeholder_literal(self, factory, registered_echo_tool, monkeypatch):
        monkeypatch.delenv("DOES_NOT_EXIST", raising=False)
        tools_config = [{"type": registered_echo_tool, "name": "my_echo", "config": {"message": "${DOES_NOT_EXIST}"}}]

        tools = factory._configure_tools(tools_config)

        assert tools[0]() == "${DOES_NOT_EXIST}"

    def test_none_config_defaults_to_empty_dict(self, factory, registered_echo_tool):
        tools_config = [{"type": registered_echo_tool, "name": "my_echo", "config": None}]

        tools = factory._configure_tools(tools_config)

        assert tools[0](message="hi") == "hi"


# --------------------------------------------------------------------------
# _configure_backend
# --------------------------------------------------------------------------


class TestConfigureBackend:
    def test_state_backend(self, factory):
        assert isinstance(factory._configure_backend({"type": "state"}), StateBackend)

    def test_missing_or_unknown_type_falls_back_to_state_backend(self, factory):
        assert isinstance(factory._configure_backend({}), StateBackend)
        assert isinstance(factory._configure_backend({"type": "bogus"}), StateBackend)

    def test_composite_backend_only_routes_store_type_entries(self, factory):
        backend = factory._configure_backend(
            {"type": "composite", "routes": {"/store_path": "store", "/other": "unrecognized"}}
        )

        assert isinstance(backend, CompositeBackend)
        assert isinstance(backend.routes["/store_path"], StoreBackend)
        assert "/other" not in backend.routes


# --------------------------------------------------------------------------
# _configure_checkpointer
# --------------------------------------------------------------------------


class TestConfigureCheckpointer:
    @pytest.mark.asyncio
    async def test_disabled_returns_none(self, factory):
        assert await factory._configure_checkpointer({"enabled": False}) is None

    @pytest.mark.asyncio
    async def test_memory_type_returns_memory_saver(self, factory):
        assert isinstance(await factory._configure_checkpointer({"type": "memory"}), MemorySaver)

    @pytest.mark.asyncio
    async def test_sqlite_type_currently_falls_back_to_memory_saver(self, factory):
        # Documented TODO in source: AsyncSqliteSaver isn't wired up yet.
        assert isinstance(await factory._configure_checkpointer({"type": "sqlite"}), MemorySaver)

    @pytest.mark.asyncio
    async def test_unknown_type_returns_none(self, factory):
        assert await factory._configure_checkpointer({"type": "bogus"}) is None

    @pytest.mark.asyncio
    async def test_postgres_type_enters_context_and_calls_setup(self, factory, monkeypatch):
        checkpointer = FakePostgresCheckpointer()
        monkeypatch.setattr(
            agent_factory_module.AsyncPostgresSaver,
            "from_conn_string",
            lambda conn_str: FakePostgresCtxMgr(checkpointer),
        )

        result = await factory._configure_checkpointer(
            {"type": "postgres", "connection_string": "postgresql://x"}
        )

        assert result is checkpointer
        assert checkpointer.setup_called is True
        assert factory._checkpointer_contexts  # kept alive for the factory's lifetime

    @pytest.mark.asyncio
    async def test_default_type_when_omitted_is_postgres(self, factory, monkeypatch):
        # Surprising default worth pinning down: an empty (but enabled) config
        # silently attempts a postgres connection rather than doing nothing.
        checkpointer = FakePostgresCheckpointer()
        monkeypatch.setattr(
            agent_factory_module.AsyncPostgresSaver,
            "from_conn_string",
            lambda conn_str: FakePostgresCtxMgr(checkpointer),
        )

        result = await factory._configure_checkpointer({})

        assert result is checkpointer


# --------------------------------------------------------------------------
# _configure_store
# --------------------------------------------------------------------------


class TestConfigureStore:
    def test_missing_or_disabled_returns_none(self, factory):
        assert factory._configure_store({}) is None
        assert factory._configure_store({"enabled": False}) is None

    def test_postgres_type_builds_store_from_resolved_connection_string(self, factory, monkeypatch):
        captured = {}

        class FakePostgresStore:
            def __init__(self, conn_str):
                captured["conn_str"] = conn_str

        monkeypatch.setattr(agent_factory_module, "PostgresStore", FakePostgresStore)
        monkeypatch.setenv("STORE_DSN", "postgresql://store-dsn")

        store = factory._configure_store(
            {"enabled": True, "type": "postgres", "connection_string": "${STORE_DSN}"}
        )

        assert isinstance(store, FakePostgresStore)
        assert captured["conn_str"] == "postgresql://store-dsn"

    def test_unknown_type_returns_none(self, factory):
        assert factory._configure_store({"enabled": True, "type": "bogus"}) is None


# --------------------------------------------------------------------------
# _configure_interrupts
# --------------------------------------------------------------------------


class TestConfigureInterrupts:
    def test_only_interrupt_mode_permissions_are_included(self, factory):
        permissions = [
            {"tool": "risky_tool", "mode": "interrupt"},
            {"tool": "safe_tool", "mode": "allow"},
        ]

        assert factory._configure_interrupts(permissions) == {"risky_tool": True}

    def test_empty_permissions_returns_empty_dict(self, factory):
        assert factory._configure_interrupts([]) == {}


# --------------------------------------------------------------------------
# _resolve_env_var / _resolve_env_vars
# --------------------------------------------------------------------------


class TestResolveEnvVars:
    def test_resolves_set_env_var(self, factory, monkeypatch):
        monkeypatch.setenv("MY_TOKEN", "secret-value")
        assert factory._resolve_env_var("${MY_TOKEN}") == "secret-value"

    def test_unset_env_var_returns_placeholder_literal(self, factory, monkeypatch):
        monkeypatch.delenv("MY_TOKEN", raising=False)
        assert factory._resolve_env_var("${MY_TOKEN}") == "${MY_TOKEN}"

    def test_non_placeholder_string_passthrough(self, factory):
        assert factory._resolve_env_var("plain-value") == "plain-value"

    def test_resolve_env_vars_recurses_into_nested_dicts_and_skips_non_strings(self, factory, monkeypatch):
        monkeypatch.setenv("NESTED_VAR", "nested-resolved")
        config = {"top": "${NESTED_VAR}", "nested": {"inner": "${NESTED_VAR}"}, "count": 5}

        resolved = factory._resolve_env_vars(config)

        assert resolved == {"top": "nested-resolved", "nested": {"inner": "nested-resolved"}, "count": 5}


# --------------------------------------------------------------------------
# get_agent / list_agents (cache access)
# --------------------------------------------------------------------------


class TestCacheAccess:
    def test_get_agent_returns_cached_instance_or_none(self, factory):
        fake_agent = object()
        factory.agents_cache["bot:tenant"] = fake_agent

        assert factory.get_agent("bot:tenant") is fake_agent
        assert factory.get_agent("missing") is None

    def test_list_agents_returns_all_cache_keys(self, factory):
        factory.agents_cache["a"] = object()
        factory.agents_cache["b:tenant"] = object()

        assert set(factory.list_agents()) == {"a", "b:tenant"}


# --------------------------------------------------------------------------
# create_from_dict — end-to-end wiring with create_deep_agent mocked out
# --------------------------------------------------------------------------


class TestCreateFromFile:
    @pytest.mark.asyncio
    async def test_reads_yaml_and_delegates_to_create_from_dict(self, factory, monkeypatch, tmp_path):
        monkeypatch.setattr(agent_factory_module, "create_deep_agent", lambda **kwargs: object())
        config_path = tmp_path / "support.yml"
        config_path.write_text("agent_id: support-bot\ncheckpointer:\n  type: memory\n")

        agent = await factory.create_from_file(str(config_path))

        assert agent.agent_id == "support-bot"
        assert factory.agents_cache["support-bot"] is agent


class TestCreateFromDict:
    @pytest.mark.asyncio
    async def test_creates_and_caches_agent_under_instance_key(self, factory, monkeypatch):
        fake_deep_agent = object()
        monkeypatch.setattr(agent_factory_module, "create_deep_agent", lambda **kwargs: fake_deep_agent)

        config = {"agent_id": "support-bot", "checkpointer": {"type": "memory"}}

        agent = await factory.create_from_dict(config, tenant_id="tenant-1")

        assert isinstance(agent, Agent)
        assert agent.agent_id == "support-bot"
        assert agent.tenant_id == "tenant-1"
        assert factory.agents_cache["support-bot:tenant-1"] is agent

    @pytest.mark.asyncio
    async def test_different_tenants_get_independent_cache_entries(self, factory, monkeypatch):
        monkeypatch.setattr(agent_factory_module, "create_deep_agent", lambda **kwargs: object())

        config = {"agent_id": "support-bot", "checkpointer": {"type": "memory"}}

        agent_a = await factory.create_from_dict(dict(config), tenant_id="tenant-a")
        agent_b = await factory.create_from_dict(dict(config), tenant_id="tenant-b")

        assert agent_a is not agent_b
        assert factory.agents_cache["support-bot:tenant-a"] is agent_a
        assert factory.agents_cache["support-bot:tenant-b"] is agent_b

    @pytest.mark.asyncio
    async def test_middleware_is_forwarded_to_create_deep_agent(self, factory, monkeypatch):
        captured = {}

        def fake_create_deep_agent(**kwargs):
            captured.update(kwargs)
            return object()

        monkeypatch.setattr(agent_factory_module, "create_deep_agent", fake_create_deep_agent)
        sentinel_middleware = [object()]

        config = {"agent_id": "support-bot", "checkpointer": {"type": "memory"}}
        await factory.create_from_dict(config, middleware=sentinel_middleware)

        assert captured["middleware"] == sentinel_middleware
