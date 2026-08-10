"""
Agent Factory - Creates agents dynamically from YAML configuration.
"""

import asyncio
import os
import yaml
import sqlite3
import logging
from typing import Dict, List, Callable, Any, Optional, Sequence
from deepagents import create_deep_agent
from langchain.agents.middleware.types import AgentMiddleware
from deepagents.backends import StateBackend, StoreBackend, CompositeBackend
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.postgres import PostgresStore

from agent_harness.tool_registry import tool_registry
from agent_harness.agent import Agent

logger = logging.getLogger(__name__)


class AgentFactory:
    """Factory for creating agents from configuration."""

    def __init__(self, token_tracker_config: Optional[Dict] = None):
        """
        Initialize agent factory.

        Args:
            token_tracker_config: Optional token tracker configuration
                - connection_string: Database connection string
                - enabled: Whether to enable token tracking (default: True if connection_string provided)

        Token Tracking Auto-Configuration:
            If token_tracker_config is not provided and DATABASE_URL environment variable exists,
            token tracking will be automatically enabled using DATABASE_URL.
            This provides zero-configuration tracking in production environments.

        LangSmith Tracing:
            LangSmith tracing is configured via configure_observability() method or
            LANGSMITH_PROJECT environment variable. See configure_observability() for details.

        Examples:
            # Auto-configure from DATABASE_URL (recommended)
            from agent_harness.agent_factory import agent_factory

            # Configure observability
            agent_factory.configure_observability(langsmith_project="my-app")

            # Configure token tracking
            agent_factory.configure_token_tracker({
                "enabled": True,
                "connection_string": "postgresql://localhost/agents"
            })

            # Now create agents
            agent = await agent_factory.create_from_file("agent.yml")
        """
        self.agents_cache: Dict[str, Agent] = {}
        # Keyed by Agent.instance_key so a single (agent_id, tenant_id) pair's
        # checkpointer pool can be closed individually on eviction — see
        # close_agent()/aclose().
        self._checkpointer_contexts: Dict[str, Any] = {}
        self._token_tracker = None
        # Guards the check-then-set below on self._token_tracker: two
        # concurrent create_from_dict calls (e.g. two different tenants'
        # very first agent build racing right after startup) could otherwise
        # both see it unset, both build their own TokenUsageTracker/pool, and
        # the loser's pool would be silently orphaned when the winner's
        # assignment overwrites it.
        self._token_tracker_lock = asyncio.Lock()

        # Auto-configure from DATABASE_URL if not explicitly provided
        if token_tracker_config is None and os.getenv("DATABASE_URL"):
            logger.debug("Auto-configuring token tracker from DATABASE_URL")
            token_tracker_config = {
                "enabled": True,
                # connection_string will be auto-detected from DATABASE_URL in _configure_token_tracker
            }

        self._token_tracker_config = token_tracker_config or {}

        # Configure observability (LangSmith tracing) - reads from env var only at init
        self._configure_observability()

    async def create_from_file(
        self,
        config_path: str,
        middleware: Optional[Sequence[AgentMiddleware]] = None,
        tenant_id: Optional[str] = None,
    ) -> Agent:
        """
        Create agent from YAML config file.

        Args:
            config_path: Path to YAML configuration file
            middleware: Optional AgentMiddleware instances (e.g. to refresh
                per-call dynamic context via `awrap_model_call`/`abefore_model`).
                Not YAML-expressible since middleware typically closes over
                live Python objects (DB sessions, per-tenant identifiers).
            tenant_id: Optional per-tenant scope — see `create_from_dict`.

        Returns:
            Configured Agent instance
        """
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        return await self.create_from_dict(config, middleware=middleware, tenant_id=tenant_id)

    async def create_from_dict(
        self,
        config: Dict,
        middleware: Optional[Sequence[AgentMiddleware]] = None,
        tenant_id: Optional[str] = None,
    ) -> Agent:
        """
        Create agent from configuration dictionary.

        Args:
            config: Agent configuration dict
            middleware: Optional AgentMiddleware instances passed through to
                `create_deep_agent`. Use this for context that must be
                refreshed on every model call (e.g. multi-tenant data that
                changes between invocations) instead of baking it into a
                static `system_prompt` — see `awrap_model_call`.
            tenant_id: Optional per-tenant scope (e.g. a workspace/customer id).
                When set, this agent is cached and its conversation memory is
                namespaced under `Agent.make_key(agent_id, tenant_id)` instead
                of the bare `agent_id` — lets one `agent_id` (one YAML config)
                serve many independent tenants, each getting its own cache slot
                and its own thread history. Leave `None` for a single-tenant
                deployment (unchanged behavior). See `TenantAgentPool` for the
                higher-level orchestration built on top of this.

        Returns:
            Configured Agent instance
        """
        agent_id = config["agent_id"]
        logger.info("Creating agent: %s", agent_id)

        # Configure tools from registry
        logger.debug("Configuring tools...")
        tools = self._configure_tools(config.get("tools", []))
        logger.info("Configured %d tools: %s", len(tools), [t.__name__ for t in tools])

        # Configure backend
        logger.debug("Configuring backend...")
        backend = self._configure_backend(config.get("backend", {}))

        # Configure checkpointer
        logger.debug("Configuring checkpointer...")
        checkpointer, checkpointer_ctx_mgr = await self._configure_checkpointer(config.get("checkpointer", {}))
        checkpointer_type = config.get("checkpointer", {}).get("type", "none")
        logger.info("Checkpointer configured: %s", checkpointer_type)

        # Configure store (if needed)
        store = self._configure_store(config.get("store", {}))

        # Extract model config
        model_config = config.get("model", {})
        model_str = f"{model_config.get('provider', 'anthropic')}:{model_config.get('name', 'claude-sonnet-4-6')}"
        logger.info("Model: %s", model_str)

        # Extract other configs
        system_prompt = config.get("system_prompt", "")

        # Configure interrupts
        interrupt_on = self._configure_interrupts(config.get("permissions", []))
        if interrupt_on:
            logger.info("Interrupts configured for tools: %s", list(interrupt_on.keys()))

        # Configure middleware
        # Note: DeepAgents automatically enables Anthropic prompt caching by default!
        # No need to manually add AnthropicPromptCachingMiddleware.
        # See: https://www.langchain.com/blog/deep-agents-prompt-caching
        middleware_list = list(middleware or ())

        # Log caching status for Anthropic models
        provider = model_config.get("provider", "anthropic")
        if provider == "anthropic":
            logger.info("✅ Prompt caching enabled (DeepAgents default for Anthropic)")

        # Create Deep Agent
        logger.debug("Creating Deep Agent...")
        deep_agent = create_deep_agent(
            model=model_str,
            tools=tools,
            system_prompt=system_prompt,
            backend=backend,
            checkpointer=checkpointer,
            store=store if store else None,
            interrupt_on=interrupt_on,
            middleware=tuple(middleware_list),
        )

        # Configure token tracker (if enabled) — see _token_tracker_lock above.
        if not self._token_tracker:
            async with self._token_tracker_lock:
                if not self._token_tracker:  # re-check: another call may have won the race
                    self._token_tracker = await self._configure_token_tracker()

        # Wrap in Agent class
        agent = Agent(agent_id, deep_agent, config, tenant_id=tenant_id, token_tracker=self._token_tracker)

        # Cache agent — keyed by the composite (agent_id, tenant_id) identity,
        # so create_from_dict can be called again for the same agent_id under a
        # different tenant_id without evicting the first tenant's instance.
        self.agents_cache[agent.instance_key] = agent
        if checkpointer_ctx_mgr is not None:
            self._checkpointer_contexts[agent.instance_key] = checkpointer_ctx_mgr

        logger.info("Agent '%s' created successfully", agent.instance_key)
        return agent

    def _configure_tools(self, tools_config: List[Dict]) -> List[Callable]:
        """Configure tools from config."""
        configured_tools = []

        for tool_spec in tools_config:
            tool_type = tool_spec["type"]
            tool_config = tool_spec.get("config", {})

            # Handle None config
            if tool_config is None:
                tool_config = {}

            # Resolve environment variables
            resolved_config = self._resolve_env_vars(tool_config)

            # Get tool from registry and configure
            configured_tool = tool_registry.configure_tool(tool_type, resolved_config, rename_as=tool_spec["name"])

            # Set description
            if "description" in tool_spec:
                configured_tool.__doc__ = tool_spec["description"]

            configured_tools.append(configured_tool)

        return configured_tools

    def _configure_backend(self, backend_config: Dict):
        """Configure backend from config."""
        backend_type = backend_config.get("type", "state")

        if backend_type == "state":
            return StateBackend()

        elif backend_type == "composite":
            default = StateBackend()
            routes = {}

            for path, store_type in backend_config.get("routes", {}).items():
                if store_type == "store":
                    routes[path] = StoreBackend()

            return CompositeBackend(default=default, routes=routes)

        else:
            return StateBackend()

    async def _configure_checkpointer(self, checkpointer_config: Dict):
        """Configure checkpointer from config.

        Returns (checkpointer, ctx_mgr) — ctx_mgr is the still-open async
        context manager backing a Postgres checkpointer (None otherwise), so
        the caller can key it under the owning agent's instance_key and close
        it later via close_agent()/aclose(), instead of it being kept alive
        forever with no way to release it individually (see close_agent()).
        """
        # Check if checkpointer is disabled
        if not checkpointer_config.get("enabled", True):
            return None, None

        cp_type = checkpointer_config.get("type", "postgres")

        if cp_type == "postgres":
            conn_str = self._resolve_env_var(checkpointer_config.get("connection_string", os.getenv("DATABASE_URL")))

            # Create and setup async checkpointer
            # We need to enter the context manager and keep it alive
            ctx_mgr = AsyncPostgresSaver.from_conn_string(conn_str)
            checkpointer = await ctx_mgr.__aenter__()
            await checkpointer.setup()
            return checkpointer, ctx_mgr

        elif cp_type == "sqlite":
            # Note: AsyncSqliteSaver requires complex setup with context managers
            # For simple testing, use memory saver instead
            # TODO: Implement proper AsyncSqliteSaver with connection management
            return MemorySaver(), None

        elif cp_type == "memory":
            return MemorySaver(), None

        return None, None

    def _configure_store(self, store_config: Dict):
        """Configure store from config."""
        if not store_config or not store_config.get("enabled"):
            return None

        store_type = store_config.get("type", "postgres")

        if store_type == "postgres":
            conn_str = self._resolve_env_var(store_config.get("connection_string", os.getenv("DATABASE_URL")))
            return PostgresStore(conn_str)

        return None

    def _configure_interrupts(self, permissions: List[Dict]) -> Dict[str, bool]:
        """Configure interrupt_on from permissions."""
        interrupt_on = {}

        for perm in permissions:
            if perm.get("mode") == "interrupt":
                tool_name = perm.get("tool")
                if tool_name:
                    interrupt_on[tool_name] = True

        return interrupt_on

    async def _configure_token_tracker(self):
        """Configure token tracker from config."""
        from agent_harness.token_tracker import TokenUsageTracker

        # Check if token tracking is disabled
        if not self._token_tracker_config.get("enabled", True):
            return None

        # Get connection string from config or env
        conn_str = self._token_tracker_config.get("connection_string")
        if not conn_str:
            # Try to reuse DATABASE_URL if available
            conn_str = os.getenv("DATABASE_URL")

        if not conn_str:
            # No connection string provided, disable tracking
            logger.debug("Token tracker disabled: no connection string provided")
            return None

        try:
            # Resolve environment variable if needed
            conn_str = self._resolve_env_var(conn_str)

            # Create and setup tracker
            tracker = TokenUsageTracker(conn_str)
            await tracker.setup()

            # Log without exposing full connection string
            db_location = conn_str.split("@")[-1] if "@" in conn_str else "local"
            logger.info("Token tracker enabled: %s", db_location)
            return tracker
        except Exception as e:
            logger.warning("Failed to initialize token tracker: %s", e, exc_info=True)
            return None

    def _resolve_env_vars(self, config: Dict) -> Dict:
        """Resolve ${ENV_VAR} placeholders in config."""
        resolved = {}

        for key, value in config.items():
            if isinstance(value, str):
                resolved[key] = self._resolve_env_var(value)
            elif isinstance(value, dict):
                resolved[key] = self._resolve_env_vars(value)
            else:
                resolved[key] = value

        return resolved

    def _resolve_env_var(self, value: str) -> str:
        """Resolve single environment variable."""
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            env_var = value[2:-1]
            return os.getenv(env_var, value)
        return value

    def _configure_observability(self, langsmith_project: Optional[str] = None):
        """
        Configure observability tools (LangSmith tracing).

        Ensures proper isolation when multiple applications use this package
        by requiring an explicit project name.

        Args:
            langsmith_project: Optional LangSmith project name for tracing.
                If not provided, will check LANGSMITH_PROJECT env var.
                If neither is set and LANGSMITH_TRACING is enabled, tracing
                will be disabled with a warning to prevent cross-app contamination.
        """
        if not os.getenv("LANGSMITH_TRACING"):
            # Tracing not enabled, nothing to do
            return

        # Priority: explicit parameter > env var > no default
        project = langsmith_project or os.getenv("LANGSMITH_PROJECT")

        if not project:
            logger.warning(
                "⚠️  LANGSMITH_TRACING is enabled but LANGSMITH_PROJECT is not set. "
                "LangSmith tracing will be DISABLED to prevent cross-app trace contamination. "
                "To enable tracing with proper isolation, set LANGSMITH_PROJECT environment variable "
                "or pass langsmith_project parameter to AgentFactory."
            )
            # Do NOT enable tracing without explicit project
            return

        # Configure LangSmith with explicit project
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_PROJECT"] = project

        # Set default endpoint if not specified
        if not os.getenv("LANGSMITH_ENDPOINT"):
            os.environ["LANGSMITH_ENDPOINT"] = "https://api.smith.langchain.com"

        logger.info("✅ LangSmith tracing enabled: project=%s", project)

    def get_agent(self, agent_id: str) -> Agent:
        """Get cached agent by ID (the composite `Agent.make_key(agent_id, tenant_id)` for tenant-scoped agents)."""
        return self.agents_cache.get(agent_id)

    def list_agents(self) -> List[str]:
        """List all cached agent IDs."""
        return list(self.agents_cache.keys())

    async def close_agent(self, agent_id: str) -> None:
        """Evict one cached agent and release its Postgres checkpointer pool.

        Dropping an agent from `agents_cache` alone (e.g. plain dict.pop, as
        `TenantAgentPool`'s LRU eviction used to do) leaves its
        `AsyncPostgresSaver` context manager — and the connection pool behind
        it — referenced forever in `_checkpointer_contexts` with no way to
        release it. `TokenUsageTracker`'s pool is a separate, factory-wide
        singleton (see `_configure_token_tracker`) and is intentionally left
        alone here — closing it would break every other still-cached agent
        sharing it; only `aclose()` (whole-process shutdown) may close it.
        """
        self.agents_cache.pop(agent_id, None)
        ctx_mgr = self._checkpointer_contexts.pop(agent_id, None)
        if ctx_mgr is not None:
            await ctx_mgr.__aexit__(None, None, None)

    async def aclose(self) -> None:
        """Release every pooled Postgres connection this factory opened.

        Nothing calls this automatically — `agents_cache`/`_token_tracker`/
        `_checkpointer_contexts` are all designed to live for the whole
        process. Call this once, from the host app's shutdown/lifespan
        teardown, so a graceful stop (or a dev `uvicorn --reload` restart)
        closes these pools instead of the event loop tearing them down mid
        `await`, which otherwise raises "Task was destroyed but it is
        pending!" (psycopg_pool's background workers) with nothing wrong
        actually broken — it's just cleanup that never ran.
        """
        for ctx_mgr in list(self._checkpointer_contexts.values()):
            await ctx_mgr.__aexit__(None, None, None)
        self._checkpointer_contexts.clear()
        self.agents_cache.clear()

        if self._token_tracker is not None:
            await self._token_tracker.close()
            self._token_tracker = None

    def configure_token_tracker(self, token_tracker_config: Dict):
        """
        Configure or reconfigure token tracker for this factory instance.

        This allows configuring the global factory instance after import,
        or reconfiguring an existing instance.

        Args:
            token_tracker_config: Token tracker configuration
                - enabled: Whether to enable tracking
                - connection_string: Database connection string (optional if DATABASE_URL is set)

        Examples:
            # Configure the global instance
            from agent_harness.agent_factory import agent_factory

            agent_factory.configure_token_tracker({
                "enabled": True,
                "connection_string": "postgresql://localhost/agents"
            })

            # Now create agents with tracking enabled
            agent = await agent_factory.create_from_file("agent.yml")

            # Disable tracking
            agent_factory.configure_token_tracker({"enabled": False})

            # Re-enable with SQLite
            agent_factory.configure_token_tracker({
                "enabled": True,
                "connection_string": "sqlite:///tokens.db"
            })
        """
        self._token_tracker_config = token_tracker_config
        # Reset tracker to force reconfiguration on next agent creation
        self._token_tracker = None
        logger.info("Token tracker configuration updated")

    def configure_observability(self, langsmith_project: Optional[str] = None):
        """
        Configure or reconfigure observability (LangSmith tracing) for this factory instance.

        This allows configuring LangSmith tracing after the factory is instantiated,
        ensuring proper isolation when multiple applications use this package.

        Args:
            langsmith_project: LangSmith project name for tracing isolation.
                If not provided and LANGSMITH_TRACING is enabled, tracing will be
                disabled with a warning to prevent cross-app trace contamination.

        Examples:
            # Configure the global instance
            from agent_harness.agent_factory import agent_factory

            agent_factory.configure_observability(langsmith_project="my-app-name")

            # Now create agents with isolated tracing
            agent = await agent_factory.create_from_file("agent.yml")
        """
        self._configure_observability(langsmith_project)


# Global factory instance with auto-configuration
# Token tracking will be automatically enabled if DATABASE_URL is set
#
# For custom configuration, create your own instance:
#   from agent_harness.agent_factory import AgentFactory
#   factory = AgentFactory(token_tracker_config={
#       "enabled": True,
#       "connection_string": "postgresql://..."
#   })
#
agent_factory = AgentFactory()
