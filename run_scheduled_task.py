#!/usr/bin/env python3
"""
Run a scheduled agent task.
Used by Kubernetes CronJobs or other schedulers.

Usage:
    python run_scheduled_task.py <agent_id> <user_id> "<prompt>"

Example:
    python run_scheduled_task.py inventory-agent system "Check stock levels"
"""

import sys
import asyncio
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from agent_harness.agent_factory import agent_factory


async def main():
    if len(sys.argv) < 4:
        print("Usage: python run_scheduled_task.py <agent_id> <user_id> \"<prompt>\"")
        sys.exit(1)

    agent_id = sys.argv[1]
    user_id = sys.argv[2]
    prompt = sys.argv[3]

    print(f"{'='*60}")
    print(f"⏰ Scheduled Task Execution")
    print(f"   Time: {datetime.now()}")
    print(f"   Agent: {agent_id}")
    print(f"   User: {user_id}")
    print(f"   Prompt: {prompt}")
    print(f"{'='*60}\n")

    try:
        # Load agent
        config_path = f"configs/agents/{agent_id}.yml"
        agent = agent_factory.create_from_file(config_path)

        # Execute task
        result = await agent.invoke(
            user_id=user_id,
            message=prompt
        )

        print(f"\n{'='*60}")
        print(f"✅ Task completed successfully")
        print(f"{'='*60}")
        print(f"\nResponse:\n{result['response']}\n")

        # Exit with success
        sys.exit(0)

    except FileNotFoundError:
        print(f"❌ Error: Agent config not found: {config_path}")
        sys.exit(1)

    except Exception as e:
        print(f"❌ Error executing task: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
