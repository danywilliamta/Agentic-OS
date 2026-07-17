"""
Agent Delegation Tool - Delegate tasks to specialized agents.
"""

from typing import Dict, Any, Optional, List
from agent_harness.tool_registry import tool_registry


@tool_registry.register(category="orchestration")
async def agent_delegation(
    target_agent_id: str,
    task_description: str,
    user_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    allowed_agents: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Délègue une tâche à un agent spécialisé.

    Args:
        target_agent_id: ID de l'agent cible (ex: 'inventory-agent', 'crm-agent')
        task_description: Description détaillée de la tâche à accomplir
        user_id: ID de l'utilisateur (optionnel, récupéré du context si absent)
        context: Contexte additionnel à passer à l'agent
        allowed_agents: Liste des agents autorisés (validation)

    Returns:
        Dict with success status and agent response
    """
    from agent_harness.agent_factory import agent_factory

    # Validate agent_id if allowed_agents provided
    if allowed_agents and target_agent_id not in allowed_agents:
        return {
            "success": False,
            "error": f"Agent '{target_agent_id}' not in allowed agents: {allowed_agents}",
            "agent": target_agent_id,
            "result": None,
        }

    try:
        # Get the target agent
        agent = agent_factory.get_agent(target_agent_id)

        if not agent:
            return {
                "success": False,
                "error": f"Agent '{target_agent_id}' not found",
                "agent": target_agent_id,
                "result": None,
            }

        # Prepare context
        final_context = context or {}
        final_user_id = user_id or final_context.get("user_id", "delegated-user")

        result = await agent.invoke(user_id=final_user_id, message=task_description, context=final_context)

        return {
            "success": True,
            "agent": target_agent_id,
            "result": result.get("response", "No response"),
            # Forwarded from the delegated agent's own invoke() — without
            # this, any tool call the delegated agent made (and its result)
            # is invisible to the delegating caller, even though invoke()
            # already exposes it one level down.
            "tool_calls": result.get("tool_calls", []),
            "metadata": result.get("metadata", {}),
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Error delegating to agent '{target_agent_id}': {str(e)}",
            "agent": target_agent_id,
            "result": None,
        }
