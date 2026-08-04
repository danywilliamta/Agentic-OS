"""
Prometheus Metrics for Agentic-OS

This module defines all Prometheus metrics for monitoring agent performance,
token usage, costs, and system health.

Usage:
    from agent_harness.metrics import (
        agent_invocations_total,
        agent_latency_seconds,
        agent_tokens_total,
        agent_cost_usd_total,
        active_threads,
        start_metrics_server
    )

    # In agent.invoke():
    with agent_latency_seconds.labels(agent_id=self.agent_id).time():
        result = await self._process_agent_response(...)
        agent_invocations_total.labels(agent_id=self.agent_id, status="success").inc()
"""

import logging
from prometheus_client import Counter, Histogram, Gauge, Info

logger = logging.getLogger(__name__)

# ==============================================================================
# AGENT INVOCATION METRICS
# ==============================================================================

agent_invocations_total = Counter(
    'agent_invocations_total',
    'Total number of agent invocations',
    ['agent_id', 'tenant_id', 'status']  # status = success|error|timeout
)

agent_latency_seconds = Histogram(
    'agent_latency_seconds',
    'Agent invocation latency in seconds',
    ['agent_id', 'tenant_id'],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]  # Buckets adaptés aux LLM
)

# ==============================================================================
# TOKEN USAGE METRICS
# ==============================================================================

agent_tokens_total = Counter(
    'agent_tokens_total',
    'Total tokens consumed by agents',
    ['agent_id', 'tenant_id', 'model', 'direction']  # direction = input|output
)

# ==============================================================================
# COST METRICS
# ==============================================================================

agent_cost_usd_total = Counter(
    'agent_cost_usd_total',
    'Total cost in USD',
    ['agent_id', 'tenant_id', 'model']
)

# ==============================================================================
# SYSTEM HEALTH METRICS
# ==============================================================================

active_threads = Gauge(
    'agent_active_threads',
    'Number of active conversation threads',
    ['agent_id', 'tenant_id']
)

# ==============================================================================
# DELEGATION METRICS
# ==============================================================================

delegations_total = Counter(
    'agent_delegations_total',
    'Total number of agent delegations',
    ['from_agent_id', 'to_agent_id', 'tenant_id', 'status']  # status = success|error
)

delegation_latency_seconds = Histogram(
    'agent_delegation_latency_seconds',
    'Delegation latency in seconds',
    ['from_agent_id', 'to_agent_id', 'tenant_id'],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 60.0]
)

# ==============================================================================
# TOOL CALL METRICS
# ==============================================================================

tool_calls_total = Counter(
    'agent_tool_calls_total',
    'Total number of tool calls',
    ['agent_id', 'tenant_id', 'tool_name', 'status']  # status = success|error|interrupted
)

tool_call_latency_seconds = Histogram(
    'agent_tool_call_latency_seconds',
    'Tool call latency in seconds',
    ['agent_id', 'tool_name'],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0]
)

# ==============================================================================
# RECURSION/ITERATION METRICS
# ==============================================================================

recursion_depth = Histogram(
    'agent_recursion_depth',
    'Number of graph iterations per invocation',
    ['agent_id', 'tenant_id'],
    buckets=[1, 3, 5, 10, 15, 20, 25, 30]
)

recursion_limit_exceeded_total = Counter(
    'agent_recursion_limit_exceeded_total',
    'Number of times recursion limit was exceeded',
    ['agent_id', 'tenant_id']
)

# ==============================================================================
# CACHE METRICS (for future semantic cache)
# ==============================================================================

cache_hits_total = Counter(
    'agent_cache_hits_total',
    'Number of cache hits',
    ['agent_id', 'cache_type']  # cache_type = semantic|exact
)

cache_misses_total = Counter(
    'agent_cache_misses_total',
    'Number of cache misses',
    ['agent_id', 'cache_type']
)

# ==============================================================================
# SYSTEM INFO
# ==============================================================================

agentic_os_info = Info(
    'agentic_os_info',
    'Information about the Agentic-OS system'
)

# Set system info at module import
agentic_os_info.info({
    'version': '1.0.0',
    'python_version': '3.11+',
    'framework': 'deepagents'
})


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def record_invocation(agent_id: str, tenant_id: str, status: str, latency: float):
    """
    Record a complete agent invocation with all metrics.

    Args:
        agent_id: Agent identifier
        tenant_id: Tenant identifier
        status: Invocation status (success|error|timeout)
        latency: Invocation duration in seconds
    """
    agent_invocations_total.labels(
        agent_id=agent_id,
        tenant_id=tenant_id or "none",
        status=status
    ).inc()

    agent_latency_seconds.labels(
        agent_id=agent_id,
        tenant_id=tenant_id or "none"
    ).observe(latency)


def record_token_usage(agent_id: str, tenant_id: str, model: str,
                      input_tokens: int, output_tokens: int,
                      cost_usd: float):
    """
    Record token usage and cost metrics.

    Args:
        agent_id: Agent identifier
        tenant_id: Tenant identifier
        model: Model name (e.g., "claude-sonnet-4-6")
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        cost_usd: Total cost in USD
    """
    # Record tokens by direction
    agent_tokens_total.labels(
        agent_id=agent_id,
        tenant_id=tenant_id or "none",
        model=model,
        direction="input"
    ).inc(input_tokens)

    agent_tokens_total.labels(
        agent_id=agent_id,
        tenant_id=tenant_id or "none",
        model=model,
        direction="output"
    ).inc(output_tokens)

    # Record cost
    agent_cost_usd_total.labels(
        agent_id=agent_id,
        tenant_id=tenant_id or "none",
        model=model
    ).inc(cost_usd)


def record_delegation(from_agent_id: str, to_agent_id: str, tenant_id: str,
                     status: str, latency: float):
    """
    Record an agent delegation.

    Args:
        from_agent_id: Source agent identifier
        to_agent_id: Target agent identifier
        tenant_id: Tenant identifier
        status: Delegation status (success|error)
        latency: Delegation duration in seconds
    """
    delegations_total.labels(
        from_agent_id=from_agent_id,
        to_agent_id=to_agent_id,
        tenant_id=tenant_id or "none",
        status=status
    ).inc()

    delegation_latency_seconds.labels(
        from_agent_id=from_agent_id,
        to_agent_id=to_agent_id,
        tenant_id=tenant_id or "none"
    ).observe(latency)


def record_tool_call(agent_id: str, tenant_id: str, tool_name: str,
                    status: str, latency: float):
    """
    Record a tool call.

    Args:
        agent_id: Agent identifier
        tenant_id: Tenant identifier
        tool_name: Name of the tool called
        status: Tool call status (success|error|interrupted)
        latency: Tool call duration in seconds
    """
    tool_calls_total.labels(
        agent_id=agent_id,
        tenant_id=tenant_id or "none",
        tool_name=tool_name,
        status=status
    ).inc()

    tool_call_latency_seconds.labels(
        agent_id=agent_id,
        tool_name=tool_name
    ).observe(latency)


# ==============================================================================
# METRICS SERVER
# ==============================================================================

def start_metrics_server(port: int = 9090):
    """
    Start Prometheus metrics HTTP server.

    This exposes a /metrics endpoint on the specified port that Prometheus
    can scrape.

    Args:
        port: Port to listen on (default: 9090)

    Example:
        # In your main application startup
        from agent_harness.metrics import start_metrics_server
        start_metrics_server(port=9090)
    """
    from prometheus_client import start_http_server

    try:
        # Listen on 0.0.0.0 to be accessible from Docker containers
        start_http_server(port, addr='0.0.0.0')
        logger.info("Prometheus metrics server started on 0.0.0.0:%d", port)
        logger.info("Metrics available at: http://localhost:%d/metrics", port)
    except OSError as e:
        if "Address already in use" in str(e):
            logger.warning("Metrics server already running on port %d", port)
        else:
            logger.error("Failed to start metrics server: %s", e)
            raise


# ==============================================================================
# FASTAPI INTEGRATION (optional)
# ==============================================================================

def create_metrics_endpoint():
    """
    Create a FastAPI endpoint for Prometheus metrics.

    Returns a Response object that can be used with FastAPI.

    Example:
        from fastapi import FastAPI, Response
        from agent_harness.metrics import create_metrics_endpoint

        app = FastAPI()

        @app.get("/metrics")
        async def metrics():
            return create_metrics_endpoint()
    """
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

    try:
        # For FastAPI Response
        from fastapi import Response
        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST
        )
    except ImportError:
        # Fallback for non-FastAPI usage
        return {
            "content": generate_latest(),
            "media_type": CONTENT_TYPE_LATEST
        }
