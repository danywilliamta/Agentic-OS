"""
Simple scheduler test - Schedule agent tasks with cron or interval.
"""

import asyncio
from datetime import datetime
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

load_dotenv()

from agent_harness.agent_factory import agent_factory


async def execute_scheduled_task(agent_id: str, user_id: str, prompt: str):
    """Execute a scheduled agent task."""

    print(f"\n{'='*60}")
    print(f"⏰ Executing scheduled task at {datetime.now()}")
    print(f"   Agent: {agent_id}")
    print(f"   Prompt: {prompt}")
    print(f"{'='*60}\n")

    try:
        # Get agent
        agent = agent_factory.get_agent(agent_id)

        if not agent:
            print(f"❌ Agent {agent_id} not found. Loading...")
            # Try to load it
            if agent_id == "inventory-agent":
                agent = agent_factory.create_from_file("configs/agents/inventory_agent.yml")
            elif agent_id == "supervisor-agent":
                agent = agent_factory.create_from_file("configs/agents/supervisor_agent.yml")
            else:
                print(f"❌ Unknown agent: {agent_id}")
                return

        # Execute task
        result = await agent.invoke(
            user_id=user_id,
            message=prompt
        )

        print(f"\n✅ Task completed successfully")
        print(f"   Response: {result['response'][:200]}...")

    except Exception as e:
        print(f"\n❌ Task failed: {e}")
        import traceback
        traceback.print_exc()


async def main():
    """Setup and start the scheduler."""

    print("""
╔══════════════════════════════════════════════════════════╗
║              SIMPLE AGENT SCHEDULER TEST                 ║
╚══════════════════════════════════════════════════════════╝
    """)

    # Create scheduler
    scheduler = AsyncIOScheduler()

    # ========================================
    # CONFIGURE YOUR SCHEDULED TASKS HERE
    # ========================================

    # Task 1: Run every 30 seconds (for testing)
    scheduler.add_job(
        execute_scheduled_task,
        trigger=IntervalTrigger(seconds=30),
        args=[
            "inventory-agent",                           # agent_id
            "scheduler-test-user",                       # user_id
            "Montre-moi le stock total de tous les produits"  # prompt
        ],
        id="task_1",
        name="Stock check (every 30s)"
    )

    # Task 2: Run every minute (cron style)
    # scheduler.add_job(
    #     execute_scheduled_task,
    #     trigger=CronTrigger(minute="*"),  # Every minute
    #     args=[
    #         "inventory-agent",
    #         "scheduler-test-user",
    #         "Vérifie les devis en attente"
    #     ],
    #     id="task_2",
    #     name="Check pending devis (every minute)"
    # )

    # Task 3: Run every day at 9am
    # scheduler.add_job(
    #     execute_scheduled_task,
    #     trigger=CronTrigger(hour=9, minute=0),  # Daily at 9am
    #     args=[
    #         "inventory-agent",
    #         "scheduler-test-user",
    #         "Génère un rapport quotidien du stock"
    #     ],
    #     id="task_3",
    #     name="Daily stock report"
    # )

    # Task 4: Run every Monday at 10am
    # scheduler.add_job(
    #     execute_scheduled_task,
    #     trigger=CronTrigger(day_of_week='mon', hour=10, minute=0),
    #     args=[
    #         "inventory-agent",
    #         "scheduler-test-user",
    #         "Rapport hebdomadaire des commandes"
    #     ],
    #     id="task_4",
    #     name="Weekly report"
    # )

    # ========================================

    # Start scheduler
    scheduler.start()

    print("\n✅ Scheduler started!")
    print("\nScheduled jobs:")
    for job in scheduler.get_jobs():
        print(f"  - [{job.id}] {job.name}")
        print(f"    Next run: {job.next_run_time}")

    print(f"\n⏳ Scheduler running... Press Ctrl+C to stop")
    print(f"{'='*60}\n")

    try:
        # Keep running
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n\n👋 Stopping scheduler...")
        scheduler.shutdown()
        print("✅ Scheduler stopped")


if __name__ == "__main__":
    asyncio.run(main())
