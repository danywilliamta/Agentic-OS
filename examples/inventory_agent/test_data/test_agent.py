"""
Test script for Inventory Agent.
Simple interactive testing of the agent harness platform.
"""

import sys
import asyncio
from pathlib import Path
from dotenv import load_dotenv

# Load environment variablesa
load_dotenv()

from agent_harness.agent_factory import agent_factory

# Get the directory where this script is located
SCRIPT_DIR = Path(__file__).parent
INVENTORY_CONFIG_PATH = SCRIPT_DIR / "inventory_agent.yml"
SUPERVISOR_CONFIG_PATH = SCRIPT_DIR / "supervisor_agent.yml"


async def test_inventory_agent():
    """Test the inventory agent with various scenarios."""

    print("🚀 Loading Agents...")
    print("-" * 60)

    # Load inventory agent first (required for supervisor delegation)
    try:
        print("📦 Loading inventory-agent...")
        inventory_agent = await agent_factory.create_from_file(str(INVENTORY_CONFIG_PATH))
        print(f"✅ Inventory Agent loaded: {inventory_agent.config['name']}")

        print("\n📦 Loading supervisor-agent...")
        agent = await agent_factory.create_from_file(str(SUPERVISOR_CONFIG_PATH))
        print(f"✅ Supervisor loaded: {agent.config['name']}")
        print(f"   Tools available: {', '.join(agent.get_tools())}")
        print("-" * 60)
    except Exception as e:
        print(f"❌ Error loading agents: {e}")
        return

    # Test user
    user_id = "test-user-1"

    # Test scenarios
    test_cases = [
        {
            "name": "Scenario 1: Consulter le stock",
            "message": "Montre-moi tous les produits en stock avec leurs quantités.",
        },
        {
            "name": "Scenario 2: Vérifier un produit spécifique",
            "message": "Combien de Laptop Dell XPS 15 sont disponibles?",
        },
        {
            "name": "Scenario 3: Consulter les devis en attente",
            "message": "Montre-moi tous les devis avec le statut 'pending'.",
        },
        {
            "name": "Scenario 4: Vérifier stock pour un devis",
            "message": "Est-ce qu'il y a assez de stock pour traiter le devis #1?",
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
            result = await agent.invoke(user_id=user_id, message=test_case["message"])

            print(f"Agent: {result['response']}")

            if result.get("metadata", {}).get("usage"):
                usage = result["metadata"]["usage"]
                print(f"\n💡 Tokens: {usage}")

        except Exception as e:
            print(f"❌ Error: {e}")

        # Wait between scenarios
        if i < len(test_cases):
            print("\n⏳ Next scenario in 2 seconds...")
            await asyncio.sleep(2)

    print(f"\n{'='*60}")
    print("✅ All test scenarios completed!")
    print(f"{'='*60}")


async def interactive_mode():
    """Interactive chat mode with the agent."""

    print("🚀 Loading Agents (Interactive Mode)...")
    print("-" * 60)

    try:
        print("📦 Loading inventory-agent...")
        inventory_agent = await agent_factory.create_from_file(str(INVENTORY_CONFIG_PATH))
        print(f"✅ Inventory Agent loaded")

        print("📦 Loading supervisor-agent...")
        agent = await agent_factory.create_from_file(str(SUPERVISOR_CONFIG_PATH))
        print(f"✅ Supervisor loaded: {agent.config['name']}")
        print(f"   Tools: {', '.join(agent.get_tools())}")
        print("\n💬 Type your messages (or 'quit' to exit)")
        print("-" * 60)
    except Exception as e:
        print(f"❌ Error loading agents: {e}")
        return

    user_id = "interactive-user"

    while True:
        try:
            # Get user input
            print("\n👤 You: ", end="")
            message = input().strip()

            if message.lower() in ["quit", "exit", "q"]:
                print("\n👋 Au revoir!")
                break

            if not message:
                continue

            # Invoke agent
            print("\n🤖 Agent: ", end="", flush=True)
            result = await agent.invoke(user_id=user_id, message=message)

            print(result["response"])

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
        asyncio.run(test_inventory_agent())


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════╗
║        INVENTORY AGENT TEST SUITE                        ║
║        Agent Harness Platform Demo                       ║
╚══════════════════════════════════════════════════════════╝
    """)
    main()
