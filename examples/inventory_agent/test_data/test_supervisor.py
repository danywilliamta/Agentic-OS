"""
Test script for Supervisor Agent with delegation.
Demonstrates multi-agent orchestration.
"""

import sys
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from agent_harness.agent_factory import agent_factory


async def test_supervisor_agent():
    """Test the supervisor agent with delegation scenarios."""

    print("🚀 Loading Supervisor Agent...")
    print("-" * 60)

    # Load both agents
    try:
        # Load inventory agent first (will be delegated to)
        inventory_agent = agent_factory.create_from_file("configs/agents/inventory_agent.yml")
        print(f"✅ Inventory Agent loaded: {inventory_agent.config['name']}")

        # Load supervisor agent
        supervisor = agent_factory.create_from_file("configs/agents/supervisor_agent.yml")
        print(f"✅ Supervisor loaded: {supervisor.config['name']}")
        print(f"   Tools available: {', '.join(supervisor.get_tools())}")
        print("-" * 60)
    except Exception as e:
        print(f"❌ Error loading agents: {e}")
        import traceback
        traceback.print_exc()
        return

    # Test user
    user_id = "test-supervisor-user"

    # Test scenarios
    test_cases = [
        {
            "name": "Scenario 1: Question simple (pas de délégation)",
            "message": "Bonjour, que peux-tu faire pour moi?"
        },
        {
            "name": "Scenario 2: Vérifier le stock (délégation à inventory)",
            "message": "Combien de Laptop Dell XPS 15 sont disponibles en stock?"
        },
        {
            "name": "Scenario 3: Consulter les devis (délégation à inventory)",
            "message": "Montre-moi tous les devis bruts en attente de traitement"
        },
    ]

    # Run test scenarios
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{'='*60}")
        print(f"📝 {test_case['name']}")
        print(f"{'='*60}")
        print(f"User: {test_case['message']}")
        print("-" * 60)

        try:
            result = await supervisor.invoke(
                user_id=user_id,
                message=test_case['message']
            )

            print(f"\n✅ Test {i} completed!")

        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()

        # Wait between scenarios
        if i < len(test_cases):
            print("\n⏳ Next scenario in 2 seconds...")
            await asyncio.sleep(2)

    print(f"\n{'='*60}")
    print("✅ All test scenarios completed!")
    print(f"{'='*60}")


async def interactive_mode():
    """Interactive chat mode with the supervisor agent."""

    print("🚀 Loading Supervisor Agent (Interactive Mode)...")
    print("-" * 60)

    try:
        # Load agents
        inventory_agent = agent_factory.create_from_file("configs/agents/inventory_agent.yml")
        supervisor = agent_factory.create_from_file("configs/agents/supervisor_agent.yml")

        print(f"✅ Loaded agents:")
        print(f"   - {inventory_agent.config['name']}")
        print(f"   - {supervisor.config['name']}")
        print(f"\n💬 Type your messages (or 'quit' to exit)")
        print("-" * 60)
    except Exception as e:
        print(f"❌ Error loading agents: {e}")
        return

    user_id = "interactive-supervisor-user"

    while True:
        try:
            # Get user input
            print("\n👤 You: ", end="")
            message = input().strip()

            if message.lower() in ['quit', 'exit', 'q']:
                print("\n👋 Au revoir!")
                break

            if not message:
                continue

            # Invoke supervisor
            print("\n🤖 Supervisor: ", end="", flush=True)
            result = await supervisor.invoke(
                user_id=user_id,
                message=message
            )

            # Response already printed by agent

        except KeyboardInterrupt:
            print("\n\n👋 Au revoir!")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")


def main():
    """Main entry point."""
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "interactive":
        asyncio.run(interactive_mode())
    else:
        asyncio.run(test_supervisor_agent())


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════╗
║     SUPERVISOR AGENT - MULTI-AGENT DELEGATION TEST       ║
║        Agent Harness Platform Demo                       ║
╚══════════════════════════════════════════════════════════╝
    """)
    main()
