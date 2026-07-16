# Agent Harness Examples

This directory contains complete working examples demonstrating different use cases and patterns with Agent Harness.

## Available Examples

### 1. [Inventory Agent](./inventory_agent/)

Complete inventory management system with:
- Stock checking and management
- PDF/TXT devis processing
- Order creation
- SQLite database integration

**Best for learning**:
- Basic agent setup
- Database tools
- PDF reading
- CRUD operations

### 2. [Supervisor Multi-Agent](./supervisor_multi_agent/)

Multi-agent orchestration with delegation:
- Supervisor agent orchestrating specialized agents
- Agent-to-agent delegation
- Task routing based on request type

**Best for learning**:
- Multi-agent patterns
- Agent delegation
- Supervisor architecture

## Running Examples

### Prerequisites

1. **Install agent-harness**:
```bash
# From repo root
pip install -e ".[all]"
```

2. **Set up environment**:
```bash
# Create .env in repo root
echo "ANTHROPIC_API_KEY=sk-ant-api03-xxxxx" > .env
```

### Run Inventory Agent

```bash
cd inventory_agent/test_data

# Initialize database
python init_db.py

# Run tests
python test_agent.py

# Interactive mode
python test_agent.py interactive
```

### Run Supervisor

```bash
cd inventory_agent/test_data

# Make sure inventory DB is initialized first
python init_db.py

# Run supervisor tests
python test_supervisor.py

# Interactive mode
python test_supervisor.py interactive
```

## Creating Your Own Example

1. **Create directory structure**:
```bash
mkdir -p examples/my_example/configs/agents
```

2. **Create agent config**:
```yaml
# examples/my_example/configs/agents/my_agent.yml
agent_id: my-agent
name: My Agent
model:
  provider: anthropic
  name: claude-sonnet-4-6
system_prompt: |
  Your agent prompt
tools:
  - name: my_tool
    type: generic_db_query
    config:
      connection_string: sqlite:///my_data.db
backend:
  type: state
checkpointer:
  type: memory
```

3. **Create test script**:
```python
# examples/my_example/test.py
import asyncio
from agent_harness import agent_factory

async def main():
    agent = agent_factory.create_from_file(
        "configs/agents/my_agent.yml"
    )

    result = await agent.invoke(
        user_id="test-user",
        message="Hello agent!"
    )

    print(result['response'])

if __name__ == "__main__":
    asyncio.run(main())
```

4. **Add README**:
```bash
# examples/my_example/README.md
# Document your example
```

## Tips

- Keep examples focused on one concept
- Include a clear README in each example
- Add sample data when relevant
- Document any prerequisites
- Show both programmatic and config-based usage

## Contributing Examples

If you create a useful example:
1. Follow the structure above
2. Test thoroughly
3. Document clearly
4. Open a merge request
