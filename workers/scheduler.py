"""
Scheduler - Handles cron jobs and scheduled triggers for agents.
"""

import asyncio
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from typing import Dict


scheduler = AsyncIOScheduler()


async def start_scheduler(agents: Dict):
    """
    Start scheduler and register cron jobs from agent configs.

    Args:
        agents: Dict of agent_id -> Agent instances
    """
    print("⏰ Starting scheduler...")

    for agent_id, agent in agents.items():
        triggers = agent.config.get("triggers", [])

        for trigger_config in triggers:
            if trigger_config.get("type") == "cron":
                schedule = trigger_config["schedule"]
                action = trigger_config.get("action", "scheduled_task")

                # Create async job for this agent + trigger
                async def job(agent=agent, action=action):
                    """Scheduled job executor."""
                    print(f"⏰ Executing scheduled task: {agent.agent_id} - {action}")

                    try:
                        result = await agent.invoke(
                            user_id=f"scheduler-{datetime.now().strftime('%Y%m%d')}",
                            message=f"Execute scheduled task: {action}"
                        )
                        print(f"✅ Scheduled task completed: {result['response'][:100]}")
                    except Exception as e:
                        print(f"❌ Scheduled task failed: {e}")

                # Parse cron schedule
                # Format: "minute hour day month day_of_week"
                # Example: "0 9 * * *" = Every day at 9 AM
                parts = schedule.split()
                if len(parts) == 5:
                    trigger = CronTrigger(
                        minute=parts[0],
                        hour=parts[1],
                        day=parts[2],
                        month=parts[3],
                        day_of_week=parts[4]
                    )

                    scheduler.add_job(
                        job,
                        trigger=trigger,
                        id=f"{agent_id}_{action}",
                        name=f"{agent_id} - {action}"
                    )

                    print(f"  ✓ Registered cron: {agent_id} - {action} ({schedule})")

    scheduler.start()
    print(f"✅ Scheduler started with {len(scheduler.get_jobs())} jobs")

    # Keep alive
    while True:
        await asyncio.sleep(3600)
