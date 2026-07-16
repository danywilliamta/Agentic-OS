# Architecture Documentation

## 🎯 Overview

This is a **generic agent harness platform** that allows creating any agent by simply writing YAML configuration files.

## 🏗️ Core Components

### 1. Tool Registry (`platform/tool_registry.py`)

**Purpose:** Central registry of all available tools.

**Key Features:**
- Register generic tools with `@tool_registry.register()`
- Configure tools with specific parameters
- Extract tool schema automatically

**Example:**
```python
@tool_registry.register(category="api")
def generic_api_call(endpoint, auth_token, ...):
    # Implementation
    pass

# Configure for specific use
instagram_tool = tool_registry.configure_tool(
    "generic_api_call",
    {"endpoint": "https://api.instagram.com", "auth_token": "..."},
    rename_as="get_instagram_posts"
)
```

### 2. Agent Factory (`platform/agent_factory.py`)

**Purpose:** Creates Deep Agents from YAML configurations.

**Process:**
1. Load YAML config
2. Resolve environment variables (`${VAR}`)
3. Configure tools from registry
4. Configure backend (State, Store, Composite)
5. Configure checkpointer (PostgreSQL)
6. Create Deep Agent
7. Wrap in Agent class
8. Cache agent instance

**Key Method:**
```python
agent = agent_factory.create_from_file("config.yml")
```

### 3. Agent Wrapper (`platform/agent.py`)

**Purpose:** Wraps Deep Agent with simplified API.

**Key Features:**
- `invoke(user_id, message, context)` - Main invocation method
- `stream_invoke()` - Streaming responses
- Automatic thread_id management
- History persistence (via Deep Agents + Checkpointer)

**Internal Flow:**
```
invoke() called
    ↓
Generate thread_id (agent_id + user_id)
    ↓
Call Deep Agents ainvoke()
    ↓ (Inside Deep Agents)
    Load history (thread_id)
    Add new message
    ReAct loop:
        Model → Tool calls → Execute → Model → ...
    Save history
    ↓
Return response
```

### 4. Generic Tools (`platform/tools/`)

**Purpose:** Reusable, parameterizable tools.

**Categories:**
- **API** (`generic_api.py`) - REST API calls, webhooks
- **Database** (`generic_db.py`) - SQL queries, writes
- **Email** (`generic_email.py`) - SMTP emails
- **Content** (`generic_content.py`) - LLM content generation

**Design Pattern:**
```python
# ONE generic tool
def generic_api_call(endpoint, auth_token, ...):
    pass

# INFINITE specific uses
instagram_api = configure(endpoint="instagram.com")
facebook_api = configure(endpoint="facebook.com")
shopify_api = configure(endpoint="shopify.com")
```

### 5. FastAPI Server (`api/main.py`)

**Purpose:** HTTP/WebSocket server for agent access.

**Endpoints:**
- `POST /api/chat/{agent_id}` - Chat (REST)
- `WS /ws/chat/{agent_id}/{user_id}` - Chat (WebSocket)
- `POST /webhook/{agent_id}` - Webhook trigger
- `GET /admin/agents` - List agents
- `GET /admin/tools` - List tools
- `GET /health` - Health check

**Startup:**
1. Load all agent configs from `configs/agents/`
2. Create agents via factory
3. Cache agents in memory
4. Start scheduler

### 6. Scheduler (`workers/scheduler.py`)

**Purpose:** Execute cron jobs from agent configs.

**Process:**
1. Parse `triggers` from agent configs
2. Register cron jobs with APScheduler
3. Execute agent invocations on schedule

**Example Config:**
```yaml
triggers:
  - type: cron
    schedule: "0 9 * * *"  # Every day 9 AM
    action: daily_report
```

## 🔄 Data Flow

### Chat Message Flow

```
User sends message via API
    ↓
FastAPI receives
    ↓
POST /api/chat/my-agent
    ↓
Get agent from cache
    ↓
agent.invoke(user_id="user-123", message="Hello")
    ↓
thread_id = "my-agent-user-123"
    ↓
Deep Agents ainvoke()
    ↓ [Inside Deep Agents]
    1. Checkpointer loads history (thread_id)
    2. Append new message
    3. ReAct loop starts:
        a. Model receives messages + available tools
        b. Model decides: tool call or final answer?
        c. If tool call: Execute tool → Add result → Loop
        d. If final answer: Return response
    4. Checkpointer saves updated history
    ↓
Response returned to user
```

### Webhook Event Flow

```
External service sends webhook
    ↓
POST /webhook/my-agent
Body: {"event": "order_received", "data": {...}}
    ↓
Create message from event
message = "Order received: ..."
    ↓
agent.invoke(user_id="webhook-{event_id}", message=message, context=event_data)
    ↓
Agent processes event
    ↓
Agent takes actions (API calls, emails, etc.)
    ↓
Response returned (status: processing)
```

### Cron Job Flow

```
Scheduler triggers (e.g., 9 AM daily)
    ↓
Scheduled job runs
    ↓
agent.invoke(user_id="scheduler-2025-01-15", message="Execute daily_report")
    ↓
Agent generates report
    ↓
Agent sends report via email tool
    ↓
Job completes
```

## 💾 Data Persistence

### Thread Isolation

Every conversation/session has a unique `thread_id`:

```
Format: "{agent_id}-{user_id}"

Examples:
- "marketing-agent-user-123"
- "crm-agent-order-456"
- "support-agent-ticket-789"
```

### PostgreSQL Schema

**Checkpoints Table** (managed by LangGraph):
```sql
CREATE TABLE checkpoints (
    thread_id VARCHAR PRIMARY KEY,
    checkpoint_ns VARCHAR,
    checkpoint JSONB,  -- Full conversation state
    metadata JSONB,
    created_at TIMESTAMP
);
```

**Store Table** (if using StoreBackend):
```sql
CREATE TABLE store (
    namespace VARCHAR[],
    key VARCHAR,
    value JSONB,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    PRIMARY KEY (namespace, key)
);
```

### History Management

**Automatic** via Deep Agents:

1. First message:
   ```python
   invoke(user_id="alice", message="Hello")
   # Saves: [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi!"}]
   ```

2. Second message:
   ```python
   invoke(user_id="alice", message="What's my name?")
   # Loads previous messages
   # Saves: [...previous..., {"role": "user", "content": "What's my name?"}, {"role": "assistant", "content": "Your name is Alice"}]
   ```

## 🧩 Configuration System

### Agent Config Structure

```yaml
# Identity
agent_id: unique-id
name: Human-readable name
description: What this agent does

# Model
model:
  provider: anthropic | openai
  name: model-name
  temperature: 0.7

# Behavior
system_prompt: |
  Multi-line prompt

# Tools (configured from registry)
tools:
  - name: tool_name_in_agent
    type: generic_tool_from_registry
    description: What this tool does
    config:
      param1: value1
      param2: ${ENV_VAR}

# Triggers
triggers:
  - type: cron
    schedule: "cron expression"
    action: action_name

# Backend
backend:
  type: state | composite
  routes:
    /path/: store

# Persistence
checkpointer:
  type: postgres
  connection_string: ${DATABASE_URL}

store:
  enabled: true | false
  type: postgres
  connection_string: ${DATABASE_URL}

# Security
permissions:
  - tool: tool_name
    mode: allow | deny | interrupt
```

### Environment Variable Resolution

**In Config:**
```yaml
config:
  api_key: ${ANTHROPIC_API_KEY}
  database: ${DATABASE_URL}
```

**Resolution:**
1. Agent Factory reads config
2. Finds `${VAR}` patterns
3. Looks up in `os.getenv("VAR")`
4. Replaces in config
5. Passes to Deep Agents

## 🔐 Security

### Tool Permissions

**Three modes:**

1. **Allow** (default):
   ```yaml
   - tool: read_data
     mode: allow
   ```
   Execute without asking.

2. **Deny**:
   ```yaml
   - tool: delete_all
     mode: deny
   ```
   Never execute, return error.

3. **Interrupt** (human-in-the-loop):
   ```yaml
   - tool: send_email
     mode: interrupt
   ```
   Pause execution, ask user approval.

**Implementation:**
- Configured in YAML
- Translated to `interrupt_on` in Deep Agents
- Deep Agents pauses at tool execution
- Returns `__interrupt__` payload
- Resume with approval/rejection

### Thread Isolation

Each user/session has separate thread_id → Separate history.

No cross-contamination between:
- Different users
- Different agents
- Different sessions

### Database Security

- PostgreSQL with password auth
- Environment variables for credentials
- No hardcoded secrets

## 🎯 Extensibility

### Adding Custom Tools

1. **Create tool function:**
   ```python
   # platform/tools/my_tool.py
   from platform.tool_registry import tool_registry

   @tool_registry.register(category="custom")
   def my_tool(param1: str) -> dict:
       """My custom tool."""
       return {"result": "..."}
   ```

2. **Import in `__init__.py`:**
   ```python
   # platform/tools/__init__.py
   from . import my_tool
   ```

3. **Use in config:**
   ```yaml
   tools:
     - name: my_custom_tool
       type: my_tool
       config:
         param1: "value"
   ```

### Adding Backends

Extend `_configure_backend()` in Agent Factory:

```python
def _configure_backend(self, config):
    backend_type = config.get("type")

    if backend_type == "my_custom_backend":
        return MyCustomBackend(...)
```

### Adding Checkpointers

Extend `_configure_checkpointer()`:

```python
def _configure_checkpointer(self, config):
    cp_type = config.get("type")

    if cp_type == "redis":
        from langgraph.checkpoint.redis import RedisSaver
        return RedisSaver(...)
```

## 📊 Scalability

### Horizontal Scaling

**Stateless Containers:**
- Agent instances created from configs
- No in-memory state (all in PostgreSQL)
- Can run N replicas

**Load Balancing:**
```
Load Balancer
    ↓
    ├─ Container 1 (agent instances)
    ├─ Container 2 (agent instances)
    └─ Container 3 (agent instances)
         ↓
    PostgreSQL (shared checkpoints)
```

### Multi-Tenancy

**Per-Tenant Configs:**
```
configs/
├── agents/
│   ├── marketing_agent_tenant_a.yml
│   ├── crm_agent_tenant_a.yml
│   ├── marketing_agent_tenant_b.yml
│   └── crm_agent_tenant_b.yml
```

**Thread Isolation:**
```
tenant_a_user_1 → thread_id: "agent-a-tenant_a_user_1"
tenant_b_user_1 → thread_id: "agent-b-tenant_b_user_1"
```

Completely isolated in PostgreSQL.

## 🚀 Deployment Patterns

### Development
```
make start
# Docker Compose with postgres
```

### Staging
```
docker build -t agent-harness:staging .
docker run -p 8000:8000 \
  -v ./configs:/app/configs \
  -e DATABASE_URL=... \
  agent-harness:staging
```

### Production (Kubernetes)
```yaml
apiVersion: apps/v1
kind: Deployment
spec:
  replicas: 5
  template:
    spec:
      containers:
      - name: platform
        image: agent-harness:prod
        volumeMounts:
        - name: configs
          mountPath: /app/configs
      volumes:
      - name: configs
        configMap:
          name: agent-configs
```

## 📈 Monitoring

### Health Checks

Built-in: `GET /health`

Returns:
```json
{
  "status": "healthy",
  "agents_count": 3,
  "tools_count": 8
}
```

### Logging

Standard Python logging:
- Agent invocations
- Tool executions
- Errors/exceptions

### Metrics (Future)

Add Prometheus:
- Request count
- Response latency
- Tool execution time
- Error rate

## 🎓 Key Takeaways

1. **Generic Tools** = One tool, infinite use cases (via configuration)
2. **YAML Configs** = No code changes to add agents
3. **Deep Agents** = Handles ReAct loop + history automatically
4. **Thread ID** = Key to history isolation
5. **Checkpointer** = Automatic persistence in PostgreSQL
6. **Factory Pattern** = YAML → Configured Agent
7. **Stateless** = Horizontal scaling easy
8. **Extensible** = Add custom tools, backends, checkpointers

## 💡 Philosophy

> **Configuration over Code**

Don't write code for each use case. Write generic code once, configure infinitely.

```
1 Generic Platform + N YAML Configs = N Agents
```

This is your **agent factory**. Ship it once, configure forever.
