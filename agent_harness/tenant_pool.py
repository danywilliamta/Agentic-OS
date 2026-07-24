"""
Tenant Agent Pool - multi-tenant orchestration on top of AgentFactory.

agent_harness's core (`AgentFactory`/`Agent`) assumes one `agent_id` = one
deployment (e.g. a single Slack support bot): a static `system_prompt` baked
into the compiled graph at creation time, and a cache keyed by the bare
`agent_id`. `TenantAgentPool` generalizes that to N agent types (one YAML
template each) x M tenants (workspaces, customers, ...), where each
(agent_type, tenant) pair needs:

- its own Agent instance (own conversation memory thread — see
  `Agent.make_key`/`Agent.instance_key`), built and cached lazily
- its own dynamic system prompt, re-read on every model call via a
  caller-supplied `context_provider` (never baked into the static
  system_prompt — see `_DynamicContextMiddleware` below), so tenant data
  changing between calls needs no cache-invalidation mechanism
- delegation wired to its siblings only (never to itself, optionally never to
  agents marked `delegatable: false`), and only once its whole tenant family
  exists in `agent_factory.agents_cache` — delegation resolves targets there

Nothing here reaches into AgentFactory/Agent internals beyond their public
API (`create_from_dict(config, middleware=, tenant_id=)`, `Agent.make_key`,
`agent_factory.get_agent`/`.agents_cache`).
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Sequence, Union

import yaml
from langchain.agents.middleware.types import AgentMiddleware, ModelRequest
from langchain_core.messages import SystemMessage

from agent_harness.agent import Agent
from agent_harness.agent_factory import agent_factory

logger = logging.getLogger(__name__)

# (tenant_id, agent_type, display_name, static_instructions) -> full system prompt.
# Owned entirely by the caller — the pool never interprets or formats the
# result, so it stays agnostic of whatever "brand brain"/business context a
# given app injects.
ContextProvider = Callable[[str, str, str, str], Awaitable[str]]


class _DynamicContextMiddleware(AgentMiddleware):
    """Rebuilds the system prompt from `context_provider` before every model call.

    Multi-tenant data can't be baked into `create_deep_agent(system_prompt=...)`
    (figé for the graph's whole lifetime) without a cache-invalidation scheme
    for every write to that data. Instead, this middleware re-derives the
    prompt on every call — the Agent (and its checkpointer) stays cached
    indefinitely, only the prompt content is ever stale-free.
    """

    def __init__(
        self,
        tenant_id: str,
        agent_type: str,
        display_name: str,
        static_instructions: str,
        context_provider: ContextProvider,
    ):
        self._tenant_id = tenant_id
        self._agent_type = agent_type
        self._display_name = display_name
        self._static_instructions = static_instructions
        self._context_provider = context_provider

    async def awrap_model_call(self, request: ModelRequest, handler):
        system_prompt = await self._context_provider(
            self._tenant_id, self._agent_type, self._display_name, self._static_instructions
        )
        fresh_request = request.override(system_message=SystemMessage(content=system_prompt))
        return await handler(fresh_request)


class TenantAgentPool:
    """
    Serves N agent types to M tenants, each (agent_type, tenant_id) pair
    getting its own cached `Agent` — built from `agent_harness.Agent`/
    `AgentFactory` without modifying either.

    YAML template fields this pool understands, in addition to the ones
    `AgentFactory` already reads:

        agent_id: <type>          # plain type id, e.g. "support_agent" — never
                                   # tenant-scoped in the template itself; the
                                   # pool composes the tenant scope on top.
        display_name: <str>       # optional, shown in delegation descriptions
                                   # (defaults to agent_id).
        delegatable: <bool>       # optional, default True. False excludes this
                                   # agent from every other agent's
                                   # `allowed_agents` (e.g. an onboarding flow
                                   # that should never be a delegation target).
        tools:
          - type: agent_delegation
            name: delegate_to_agent
            ...                    # `allowed_agents`/`description` are filled
                                    # in by the pool from sibling agent_types.
          - type: some_tool
            name: some_tool
            tenant_param: workspace_id   # optional: the pool curries
                                          # `tenant_id` into this config key
                                          # before AgentFactory builds the
                                          # tool — the LLM never sees it.
    """

    def __init__(
        self,
        configs_dir: Union[str, Path],
        agent_types: Sequence[str],
        context_provider: ContextProvider,
        max_cached_tenants: int = 200,
    ):
        self._configs_dir = Path(configs_dir)
        self._agent_types = list(agent_types)
        self._context_provider = context_provider
        self._max_cached_tenants = max_cached_tenants
        # Tracks recency at tenant granularity — a "slot" here is one tenant
        # (its whole agent family evicted together), not one agent instance.
        self._tenant_order: "OrderedDict[str, None]" = OrderedDict()
        self._templates: Dict[str, dict] = {}

    def _load_template(self, agent_type: str) -> dict:
        if agent_type not in self._templates:
            path = self._configs_dir / f"{agent_type}.yml"
            with open(path, "r", encoding="utf-8") as f:
                self._templates[agent_type] = yaml.safe_load(f)
        return self._templates[agent_type]

    def _render_tool_spec(
        self, tool_spec: dict, tenant_id: str, agent_type: str, sibling_keys: Dict[str, str]
    ) -> dict:
        """Curry per-tenant/per-agent values into a tool spec's config."""
        rendered = dict(tool_spec)
        config = dict(rendered.get("config") or {})

        if rendered["type"] == "agent_delegation":
            allowed = [
                key
                for other_type, key in sibling_keys.items()
                if other_type != agent_type and self._load_template(other_type).get("delegatable", True)
            ]
            config["allowed_agents"] = allowed
            # The generic agent_delegation docstring ('ex: inventory-agent')
            # says nothing about the real composite format — without an exact
            # list, the LLM invents a plausible-looking target_agent_id that
            # never matches allowed_agents.
            rendered["description"] = (
                "Delegates a task to a specialized teammate agent. `target_agent_id` "
                "must be EXACTLY one of the following (copy verbatim, never shorten, "
                "never invent another format):\n"
                + "\n".join(
                    f'- "{key}" -> {self._load_template(other_type).get("display_name", other_type)}'
                    for other_type, key in sibling_keys.items()
                    if key in allowed
                )
            )
        elif "tenant_param" in rendered:
            rendered = dict(rendered)
            param = rendered.pop("tenant_param")
            config[param] = tenant_id

        rendered["config"] = config
        return rendered

    async def _build_agent(self, tenant_id: str, agent_type: str, sibling_keys: Dict[str, str]) -> Agent:
        template = self._load_template(agent_type)
        instructions = template.get("system_prompt", "")
        display_name = template.get("display_name", agent_type)

        config = dict(template)
        config["system_prompt"] = ""  # injected per-call by _DynamicContextMiddleware
        config["tools"] = [
            self._render_tool_spec(spec, tenant_id, agent_type, sibling_keys)
            for spec in template.get("tools", [])
        ]

        middleware = [
            _DynamicContextMiddleware(
                tenant_id, agent_type, display_name, instructions, self._context_provider
            )
        ]
        return await agent_factory.create_from_dict(config, middleware=middleware, tenant_id=tenant_id)

    def _evict_if_needed(self) -> None:
        while len(self._tenant_order) > self._max_cached_tenants:
            oldest_tenant, _ = self._tenant_order.popitem(last=False)
            for agent_type in self._agent_types:
                agent_factory.agents_cache.pop(Agent.make_key(agent_type, oldest_tenant), None)
            logger.info("TenantAgentPool: evicted tenant %s (LRU)", oldest_tenant)

    async def _build_tenant_family(self, tenant_id: str) -> Dict[str, Agent]:
        sibling_keys = {t: Agent.make_key(t, tenant_id) for t in self._agent_types}

        family: Dict[str, Agent] = {}
        for agent_type in self._agent_types:
            family[agent_type] = await self._build_agent(tenant_id, agent_type, sibling_keys)

        self._tenant_order[tenant_id] = None
        self._tenant_order.move_to_end(tenant_id)
        self._evict_if_needed()
        return family

    async def get_agent(self, tenant_id: str, agent_type: str) -> Agent:
        """Return the Agent for (tenant_id, agent_type), building it if needed.

        Building one agent_type for a tenant builds that tenant's *whole*
        family together: delegation resolves its targets by looking them up
        in `agent_factory.agents_cache`, so siblings must already exist there
        by the time any one of them is first invoked.
        """
        if agent_type not in self._agent_types:
            raise ValueError(f"Unknown agent_type: {agent_type!r} (expected one of {self._agent_types})")

        key = Agent.make_key(agent_type, tenant_id)
        cached = agent_factory.get_agent(key)
        if cached is not None:
            self._tenant_order.move_to_end(tenant_id)
            return cached

        family = await self._build_tenant_family(tenant_id)
        return family[agent_type]
