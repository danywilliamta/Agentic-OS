"""
Agent Harness - A production-ready OS for LLM agents.

Provides:
- Multi-agent orchestration and delegation
- Tool registry for reusable tools
- Agent factory for easy configuration
- Production deployment patterns (K8s, Docker)

Quick start:
    >>> from agent_harness import agent_factory
    >>> agent = agent_factory.create_from_file("my_agent.yml")
    >>> result = await agent.invoke(user_id="user123", message="Hello")

Using tools directly:
    >>> from agent_harness import read_pdf, generic_db_query, agent_delegation
    >>> pdf_content = read_pdf("document.pdf")
    >>> db_result = generic_db_query("sqlite:///data.db", "SELECT * FROM users")
    >>> delegation_result = await agent_delegation("inventory-agent", "Check stock")
"""

from agent_harness.__version__ import (
    __version__,
    __title__,
    __description__,
    __author__,
    __author_email__,
    __license__,
)

from agent_harness.agent import Agent
from agent_harness.agent_factory import AgentFactory, agent_factory
from agent_harness.tool_registry import ToolRegistry, tool_registry
from agent_harness.tenant_pool import TenantAgentPool

# Import tools to register them
from agent_harness import tools

# Import specific tools for public API
from agent_harness.tools.agent_delegation import agent_delegation
from agent_harness.tools.generic_api import generic_api_call, generic_webhook_sender
from agent_harness.tools.generic_db import generic_db_query, generic_db_write
from agent_harness.tools.pdf_reader import read_pdf

__all__ = [
    # Version info
    "__version__",
    "__title__",
    "__description__",
    "__author__",
    "__author_email__",
    "__license__",
    # Core classes
    "Agent",
    "AgentFactory",
    "agent_factory",
    "ToolRegistry",
    "tool_registry",
    "TenantAgentPool",
    # Submodules
    "tools",
    # Public tools
    "agent_delegation",
    "generic_api_call",
    "generic_webhook_sender",
    "generic_db_query",
    "generic_db_write",
    "read_pdf",
]