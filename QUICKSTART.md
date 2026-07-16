# Quick Start Guide

Get your agent harness running in 5 minutes.

## Prerequisites

- Docker & Docker Compose
- (OR) Python 3.11+ with PostgreSQL

## 🚀 5-Minute Setup

### Step 1: Environment

```bash
cd agent-harness-platform
cp .env.example .env
```

Edit `.env` and add your API key:
```bash
ANTHROPIC_API_KEY=sk-ant-your-key-here
# OR
OPENAI_API_KEY=sk-your-key-here
```

### Step 2: Create Agent Config

```bash
cp configs/agents/example_agent.yml configs/agents/my_agent.yml
```

Edit `my_agent.yml` - minimal example:
```yaml
agent_id: my-agent
name: My First Agent

model:
  provider: anthropic
  name: claude-sonnet-4-6

system_prompt: |
  You are a helpful assistant.

tools:
  - name: generate_content
    type: generic_content_generator
    config:
      llm_provider: anthropic
      api_key: ${ANTHROPIC_API_KEY}
      model: claude-sonnet-4-6

backend:
  type: state

checkpointer:
  type: postgres
  connection_string: ${DATABASE_URL}
```

### Step 3: Start

```bash
make start
# OR
./start.sh
# OR
docker-compose up -d
```

Wait ~10 seconds for startup.

### Step 4: Test

```bash
# Health check
curl http://localhost:8000/health

# Chat with your agent
curl -X POST http://localhost:8000/api/chat/my-agent \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test-user",
    "message": "Hello! Generate a short poem about AI."
  }'
```

**Done!** 🎉

## 📚 What Just Happened?

1. **Docker Compose** started:
   - Platform container (your agent harness)
   - PostgreSQL (for checkpoints/history)
   - Redis (optional, for future use)

2. **Platform loaded** your agent config:
   - Registered tools from config
   - Created Deep Agent
   - Started FastAPI server

3. **Your message** triggered:
   - ReAct loop (model → tool → model → response)
   - History saved to PostgreSQL
   - Response returned

## 🎯 Next Steps

### Add More Tools

Edit `my_agent.yml`:

```yaml
tools:
  # Call any API
  - name: call_my_api
    type: generic_api_call
    config:
      endpoint: https://api.myservice.com/data
      method: GET
      auth_type: bearer
      auth_token: ${MY_API_TOKEN}

  # Query database
  - name: query_data
    type: generic_db_query
    config:
      connection_string: ${DATABASE_URL}

  # Send emails
  - name: send_email
    type: generic_email_sender
    config:
      smtp_host: smtp.gmail.com
      smtp_port: 587
      smtp_user: ${SMTP_USER}
      smtp_password: ${SMTP_PASSWORD}
      from_email: ${SMTP_USER}
```

Restart:
```bash
docker-compose restart platform
```

### Add Cron Jobs

Edit `my_agent.yml`:

```yaml
triggers:
  - type: cron
    schedule: "0 9 * * *"  # Every day at 9 AM
    action: daily_report

  - type: cron
    schedule: "0 */4 * * *"  # Every 4 hours
    action: check_status
```

### Add Second Agent

```bash
cp configs/agents/my_agent.yml configs/agents/assistant_agent.yml
```

Edit `assistant_agent.yml`:
```yaml
agent_id: assistant-agent  # Change this!
name: Assistant Agent
# ... customize ...
```

Restart → Now you have 2 agents!

### WebSocket Chat

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/chat/my-agent/user-123');

ws.onopen = () => {
  ws.send(JSON.stringify({
    message: "Hello via WebSocket!"
  }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Agent:', data.response);
};
```

### Webhooks

External services can trigger your agent:

```bash
curl -X POST http://localhost:8000/webhook/my-agent \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "order_received",
    "id": "order-123",
    "data": {"customer": "john@example.com"}
  }'
```

## 🔍 Explore

### View Loaded Agents
```bash
curl http://localhost:8000/admin/agents | python -m json.tool
```

### View Available Tools
```bash
curl http://localhost:8000/admin/tools | python -m json.tool
```

### View Logs
```bash
docker-compose logs -f platform
```

## 🛠️ Troubleshooting

### Port already in use
```bash
# Change port in docker-compose.yml
ports:
  - "8001:8000"  # Use 8001 instead
```

### Agent not loading
```bash
# Check logs
docker-compose logs platform

# Common issues:
# - Missing environment variable
# - YAML syntax error
# - Invalid tool type
```

### Database connection error
```bash
# Check if postgres is running
docker-compose ps

# Recreate database
docker-compose down -v
docker-compose up -d
```

## 📖 Learn More

- [README.md](README.md) - Full documentation
- [ARCHITECTURE.md](ARCHITECTURE.md) - Architecture deep dive
- `configs/agents/example_agent.yml` - Full config example

## 🆘 Common Commands

```bash
# Start
make start

# Stop
make stop

# Restart
make restart

# View logs
make logs

# Test API
make test

# Clean everything
make clean
```

## 🎯 Production Checklist

Before deploying to production:

- [ ] Change PostgreSQL password (`.env` + `docker-compose.yml`)
- [ ] Use external PostgreSQL (not docker)
- [ ] Add HTTPS/SSL
- [ ] Configure CORS properly
- [ ] Set resource limits in docker-compose
- [ ] Add monitoring (Prometheus, Grafana)
- [ ] Set up log aggregation
- [ ] Add authentication/authorization
- [ ] Test horizontally scaling (multiple containers)
- [ ] Set up backups (PostgreSQL)

## 💡 Tips

**Multiple environments:**
```bash
# .env.dev
# .env.staging
# .env.prod

docker-compose --env-file .env.prod up -d
```

**Separate configs per environment:**
```
configs/
├── agents/
│   ├── dev/
│   ├── staging/
│   └── prod/
```

**Use secrets manager (production):**
```yaml
# Don't use .env in production
# Use AWS Secrets Manager, Vault, etc.
config:
  api_key: ${AWS_SECRET_API_KEY}
```

## ✅ Success!

You now have a running agent harness platform!

**What you built:**
- Generic platform (1 codebase)
- Configurable agents (N configs)
- Multi-tool support (∞ APIs, DBs, services)
- Automatic history (PostgreSQL)
- Cron jobs (scheduled tasks)
- Webhooks (event-driven)
- REST + WebSocket APIs

**Next:** Customize for your use case! 🚀
