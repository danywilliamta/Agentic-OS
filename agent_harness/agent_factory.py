"""
Agent Factory - Creates agents dynamically from YAML configuration.
"""

import os
import yaml
import sqlite3
from typing import Dict, List, Callable, Any
from deepagents import create_deep_agent
from deepagents.backends import StateBackend, StoreBackend, CompositeBackend
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.postgres import PostgresStore

from agent_harness.tool_registry import tool_registry
from agent_harness.agent import Agent


class AgentFactory:
    """Factory for creating agents from configuration."""

    def __init__(self):
        self.agents_cache: Dict[str, Agent] = {}

    def create_from_file(self, config_path: str) -> Agent:
        """
        Create agent from YAML config file.

        Args:
            config_path: Path to YAML configuration file

        Returns:
            Configured Agent instance
        """
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        return self.create_from_dict(config)

    def create_from_dict(self, config: Dict) -> Agent:
        """
        Create agent from configuration dictionary.

        Args:
            config: Agent configuration dict

        Returns:
            Configured Agent instance
        """
        agent_id = config["agent_id"]
        print(f"\n🔧 Creating agent: {agent_id}")

        # Configure tools from registry
        print(f"📦 Configuring tools...")
        tools = self._configure_tools(config.get("tools", []))
        print(f"✅ Configured {len(tools)} tools: {[t.__name__ for t in tools]}")

        # Configure backend
        print(f"🗄️  Configuring backend...")
        backend = self._configure_backend(config.get("backend", {}))

        # Configure checkpointer
        print(f"💾 Configuring checkpointer...")
        checkpointer = self._configure_checkpointer(config.get("checkpointer", {}))
        checkpointer_type = config.get("checkpointer", {}).get("type", "none")
        print(f"✅ Checkpointer: {checkpointer_type}")

        # Configure store (if needed)
        store = self._configure_store(config.get("store", {}))

        # Extract model config
        model_config = config.get("model", {})
        model_str = f"{model_config.get('provider', 'anthropic')}:{model_config.get('name', 'claude-sonnet-4-6')}"
        print(f"🤖 Model: {model_str}")

        # Extract other configs
        system_prompt = config.get("system_prompt", "")

        # Configure interrupts
        interrupt_on = self._configure_interrupts(config.get("permissions", []))
        if interrupt_on:
            print(f"⏸️  Interrupts on: {list(interrupt_on.keys())}")

        # Create Deep Agent
        print(f"🚀 Creating Deep Agent...")
        deep_agent = create_deep_agent(
            model=model_str,
            tools=tools,
            system_prompt=system_prompt,
            backend=backend,
            checkpointer=checkpointer,
            store=store if store else None,
            interrupt_on=interrupt_on,
        )

        # Wrap in Agent class
        agent = Agent(agent_id, deep_agent, config)

        # Cache agent
        self.agents_cache[agent_id] = agent

        print(f"✅ Agent '{agent_id}' created successfully!\n")
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

    def _configure_checkpointer(self, checkpointer_config: Dict):
        """Configure checkpointer from config."""
        # Check if checkpointer is disabled
        if not checkpointer_config.get("enabled", True):
            return None

        cp_type = checkpointer_config.get("type", "postgres")

        if cp_type == "postgres":
            conn_str = self._resolve_env_var(checkpointer_config.get("connection_string", os.getenv("DATABASE_URL")))
            pool_size = checkpointer_config.get("pool_size", 10)  # Default: 10 connections
            return PostgresSaver(conn_str, pool_size=pool_size)

        elif cp_type == "sqlite":
            # Note: AsyncSqliteSaver requires complex setup with context managers
            # For simple testing, use memory saver instead
            # TODO: Implement proper AsyncSqliteSaver with connection management
            return MemorySaver()

        elif cp_type == "memory":
            return MemorySaver()

        return None

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

    def get_agent(self, agent_id: str) -> Agent:
        """Get cached agent by ID."""
        return self.agents_cache.get(agent_id)

    def list_agents(self) -> List[str]:
        """List all cached agent IDs."""
        return list(self.agents_cache.keys())


# Global factory instance
agent_factory = AgentFactory()
