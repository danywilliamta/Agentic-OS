# Agent Harness

> A production-ready OS for LLM agents - Multi-agent orchestration, tool registry, and delegation

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Agent Harness** is a framework for building, orchestrating, and deploying LLM agents in production. It provides the infrastructure layer that lets you focus on agent behavior, not plumbing.

## Features

- 🤖 **Agent Factory**: Create agents from YAML configs or Python dicts
- 🔧 **Tool Registry**: Reusable, configurable tools (DB, API, PDF, email, etc.)
- 🎯 **Multi-Agent Orchestration**: Supervisor pattern with delegation
- 💾 **Persistence**: PostgreSQL/SQLite checkpointing for conversation state
- 📊 **Token Tracking**: Automatic cost tracking and usage analytics per agent/user/tenant
- ⏰ **Scheduling**: Cron-style task scheduling (APScheduler + K8s CronJobs)
- 🚀 **Production-Ready**: Docker, K8s manifests, CI/CD examples
- 🔒 **Permissions**: Interrupt-based approval for sensitive operations

## Quick Start

### Installation

```bash
# From Git (private repo)
pip install git+https://gitlab.com/your-org/agent-harness.git

# Or clone and install locally
git clone https://gitlab.com/your-org/agent-harness.git
cd agent-harness
pip install -e .

# With optional dependencies
pip install -e ".[all]"  # All features
pip install -e ".[pdf,postgres]"  # Specific features
```

### Your First Agent

1. **Create agent config** (`my_agent.yml`):

```yaml
agent_id: my-agent
name: My First Agent
model:
  provider: anthropic
  name: claude-sonnet-4-6

system_prompt: |
  You are a helpful assistant.

tools:
  - name: query_database
    type: generic_db_query
    config:
      connection_string: sqlite:///my_data.db

backend:
  type: state

checkpointer:
  type: memory
```

2. **Use the agent**:

```python
import asyncio
from agent_harness import agent_factory

async def main():
    # Load agent
    agent = agent_factory.create_from_file("my_agent.yml")

    # Invoke
    result = await agent.invoke(
        user_id="user123",
        message="What data do we have?"
    )

    print(result['response'])

asyncio.run(main())
```

## Examples

See [`examples/`](./examples/) for complete working examples:

- **[Inventory Agent](./examples/inventory_agent/)**: Stock management, devis processing, order creation
- **[Supervisor Multi-Agent](./examples/supervisor_multi_agent/)**: Orchestrator with delegation

## Architecture

```
┌─────────────────────────────────────────────┐
│           Your Application                  │
│  from agent_harness import agent_factory    │
└──────────────────┬──────────────────────────┘
                   ↓
┌─────────────────────────────────────────────┐
│          Agent Harness (Core)               │
│  ┌────────────┐  ┌─────────────┐           │
│  │ Agent      │  │ Tool        │           │
│  │ Factory    │  │ Registry    │           │
│  └────────────┘  └─────────────┘           │
└──────────────────┬──────────────────────────┘
                   ↓
┌─────────────────────────────────────────────┐
│         DeepAgents / LangGraph              │
│         (Anthropic's agent SDK)             │
└─────────────────────────────────────────────┘
```

## Core Concepts

### Agent Factory

Create agents from YAML or dict configs:

```python
from agent_harness import agent_factory

# From file
agent = agent_factory.create_from_file("agent.yml")

# From dict
agent = agent_factory.create_from_dict({
    "agent_id": "my-agent",
    "model": {"provider": "anthropic", "name": "claude-sonnet-4-6"},
    "tools": [...]
})
```

### Tool Registry

Register and configure reusable tools:

```python
from agent_harness import tool_registry

@tool_registry.register(category="custom")
def my_tool(param: str) -> dict:
    return {"result": f"Processed: {param}"}

# Tool is now available in agent configs
```

Built-in tools:
- `generic_db_query` / `generic_db_write` - SQL databases
- `generic_api_call` - HTTP APIs
- `read_pdf` - PDF/TXT file reading
- `send_email` - Email sending
- `agent_delegation` - Multi-agent delegation

### Multi-Agent Orchestration

Supervisor pattern with delegation:

```python
# Supervisor delegates to specialized agents
supervisor = agent_factory.create_from_file("supervisor.yml")
inventory_agent = agent_factory.create_from_file("inventory.yml")

result = await supervisor.invoke(
    user_id="user123",
    message="Check stock levels"
)
# Supervisor automatically delegates to inventory_agent
```

### Token Tracking

Built-in cost tracking and usage analytics with zero configuration:

```python
from agent_harness import agent_factory

# Token tracking auto-enabled if DATABASE_URL is set
# No configuration needed!
agent = await agent_factory.create_from_file("agent.yml")
result = await agent.invoke(user_id="user123", message="Hello")

# Usage automatically logged to database
print(result["metadata"]["usage"])
# {'input_tokens': 150, 'output_tokens': 50}

# Analyze costs via CLI
# python scripts/analyze_token_usage.py --agent-id my-agent
# python scripts/analyze_token_usage.py --top-consumers tenant_id

# Or programmatically
from agent_harness.token_tracker import TokenUsageTracker

tracker = TokenUsageTracker("postgresql://localhost/agents")
await tracker.setup()

stats = await tracker.get_usage_stats(agent_id="my-agent")
print(f"Total cost: ${stats['total_cost_usd']:.2f}")
print(f"Total tokens: {stats['total_tokens']:,}")
```

**Auto-Configuration**: If `DATABASE_URL` environment variable is set, token tracking is automatically enabled. No code changes required.

See [`docs/TOKEN_TRACKING.md`](./docs/TOKEN_TRACKING.md) and [`docs/FACTORY_USAGE.md`](./docs/FACTORY_USAGE.md) for full documentation.

---

### 📊 Observability & Monitoring

#### Prometheus Metrics

Agent Harness automatically collects Prometheus metrics (latency, tokens, costs, errors). No code changes required!

**📍 Choose your deployment pattern:**

**For Development / Single Process:**
```bash
# Start standalone metrics server
poetry run python scripts/metrics_server.py
# Metrics available at http://localhost:9090/metrics

# Start Prometheus
docker-compose -f docker-compose.prometheus.yml up -d
# Prometheus UI: http://localhost:9091
```

**For Production / Multiple Workers:** ⭐ **RECOMMENDED**
```bash
# Use multiprocess mode with metrics collector
docker-compose -f docker-compose.multiworker.yml up -d

# Access:
# - Application: http://localhost:8000
# - Metrics: http://localhost:9090/metrics
# - Prometheus: http://localhost:9091
```

**Documentation:**
- Single process setup: [`docs/PROMETHEUS.md`](./docs/PROMETHEUS.md)
- **Multiple workers setup: [`docs/PROMETHEUS_MULTIPROCESS.md`](./docs/PROMETHEUS_MULTIPROCESS.md)** ← Read this for production!

---

#### ⚠️ LangSmith Tracing Isolation (IMPORTANT for Multi-App)

**If multiple applications use this package**, you MUST specify a unique project name to prevent trace contamination:

```python
from agent_harness.agent_factory import agent_factory

# ✅ CORRECT: Configure observability with unique project name
agent_factory.configure_observability(langsmith_project="my-app-name")

# Now create agents (traces will go to "my-app-name" project)
agent = await agent_factory.create_from_file("agent.yml")
```

**Or via environment variable:**
```bash
export LANGSMITH_TRACING=true
export LANGSMITH_PROJECT=my-app-name  # REQUIRED for isolation
```

**Example for multiple apps:**
```python
# App A (CRM)
from agent_harness.agent_factory import agent_factory
agent_factory.configure_observability(langsmith_project="crm-app")

# App B (Support)
from agent_harness.agent_factory import agent_factory
agent_factory.configure_observability(langsmith_project="support-app")
```

**Why this matters:**
- Without explicit project, tracing is **disabled by default** to prevent cross-app trace contamination
- Each app must specify its own unique project name for proper isolation
- Traces from App A will NOT mix with traces from App B

See [`AUDIT_RECOMMENDATIONS.md`](./AUDIT_RECOMMENDATIONS.md#-problème-disolation-langsmith-multi-app) for detailed explanation.

## Installation Options

```bash
# Core only (minimal dependencies)
pip install agent-harness

# With PDF support
pip install agent-harness[pdf]

# With API server
pip install agent-harness[api]

# With PostgreSQL
pip install agent-harness[postgres]

# With SQLite
pip install agent-harness[sqlite]

# With scheduler
pip install agent-harness[scheduler]

# Everything
pip install agent-harness[all]
```

## Production Deployment

### Docker

```bash
docker build -t agent-harness:latest .
docker run -e ANTHROPIC_API_KEY=xxx agent-harness:latest
```

### Kubernetes CronJobs

```bash
# Deploy scheduled tasks
kubectl apply -f k8s/cronjobs/
```

See [`k8s/README.md`](./k8s/README.md) for detailed K8s deployment guide.

## Configuration

### Agent Config

```yaml
agent_id: my-agent
name: My Agent
description: Agent description

model:
  provider: anthropic
  name: claude-sonnet-4-6
  temperature: 0.7

system_prompt: |
  Your system prompt here

tools:
  - name: tool_name
    type: generic_db_query
    description: Tool description
    config:
      # Tool-specific config
      connection_string: postgresql://...

backend:
  type: state

checkpointer:
  type: postgres
  connection_string: ${DATABASE_URL}

permissions:
  - tool: write_database
    mode: interrupt  # require approval
  - tool: query_database
    mode: allow  # auto-approve
```

### Environment Variables

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-api03-xxxxx
DATABASE_URL=postgresql://user:pass@host:5432/db
```

## Development

### Setup

```bash
# Clone repo
git clone https://gitlab.com/your-org/agent-harness.git
cd agent-harness

# Install with dev dependencies
poetry install --with dev

# Or with pip
pip install -e ".[all,dev]"
```

### Run Examples

```bash
# Inventory agent example
cd examples/inventory_agent/test_data
python init_db.py  # Setup DB
python test_agent.py  # Run tests

# Supervisor example
python test_supervisor.py interactive
```

### Project Structure

```
agent-harness/
├── agent_harness/          # Core package
│   ├── agent.py
│   ├── agent_factory.py
│   ├── tool_registry.py
│   └── tools/
├── examples/               # Usage examples
├── k8s/                    # K8s manifests
├── docs/                   # Documentation
└── pyproject.toml          # Package config
```

## Contributing

This is a private project. Contact the maintainer for contribution guidelines.

## License

MIT License

## Support

For issues or questions:
- Open an issue on GitLab
- Contact: dany-william.tagne@mfglabs.com

---

Built with ❤️ using [DeepAgents](https://github.com/anthropics/deepagents) and [LangGraph](https://github.com/langchain-ai/langgraph)
