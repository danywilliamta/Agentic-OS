#!/bin/bash

echo "🚀 Starting Agent Harness Platform..."

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  .env file not found. Creating from template..."
    cp .env.example .env
    echo "✅ Created .env file. Please edit it with your API keys."
    echo ""
    echo "Required:"
    echo "  - ANTHROPIC_API_KEY or OPENAI_API_KEY"
    echo "  - DATABASE_URL (or use docker-compose postgres)"
    echo ""
    read -p "Press enter when ready..."
fi

# Check if configs/agents has any yml files besides example
AGENT_COUNT=$(find configs/agents -name "*.yml" ! -name "example_agent.yml" | wc -l)

if [ "$AGENT_COUNT" -eq 0 ]; then
    echo "⚠️  No agent configs found (besides example)."
    echo ""
    echo "Create your first agent:"
    echo "  cp configs/agents/example_agent.yml configs/agents/my_agent.yml"
    echo "  nano configs/agents/my_agent.yml"
    echo ""
    read -p "Press enter to continue with example agent..."
fi

# Start with docker-compose
echo ""
echo "Starting with Docker Compose..."
echo ""
docker-compose up -d

echo ""
echo "✅ Platform started!"
echo ""
echo "Services:"
echo "  - API: http://localhost:8000"
echo "  - Health: http://localhost:8000/health"
echo "  - Admin: http://localhost:8000/admin/agents"
echo "  - PostgreSQL: localhost:5432"
echo ""
echo "Logs:"
echo "  docker-compose logs -f platform"
echo ""
echo "Stop:"
echo "  docker-compose down"
echo ""
