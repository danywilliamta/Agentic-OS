"""
Agent Wrapper - Wraps Deep Agent with invoke and history management.
"""

import logging
import time
from typing import Dict, List, Any, Optional, TYPE_CHECKING
from deepagents import create_deep_agent
from langgraph.types import Command
from langgraph.errors import GraphRecursionError

if TYPE_CHECKING:
    from agent_harness.token_tracker import TokenUsageTracker

logger = logging.getLogger(__name__)

# Import metrics (optional - only if prometheus_client is installed)
try:
    from agent_harness.metrics import (
        record_invocation,
        record_token_usage,
        recursion_limit_exceeded_total
    )
    METRICS_ENABLED = True
except ImportError:
    METRICS_ENABLED = False
    logger.debug("Prometheus metrics not available (prometheus_client not installed)")


def _extract_text(raw_content) -> str:
    """
    Extract plain text from a message's `content`.

    Content blocks aren't always `[text]` or `[text, ...]` — extended thinking
    models commonly emit `[thinking, text]` or end a tool-only turn with no
    text block at all (e.g. a "silent" tool call). Scanning by index 0 alone
    misidentifies both cases; scan every block for text instead, and fall
    back to "" (not `str(raw_content)`) when none is found — an empty turn is
    a legitimate outcome, not something to surface as literal Python repr.
    """
    if isinstance(raw_content, list):
        text_parts = [
            block.get("text", "") for block in raw_content if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "\n".join(part for part in text_parts if part)
    if isinstance(raw_content, str):
        return raw_content
    return str(raw_content) if raw_content else ""


class Agent:
    """
    Agent wrapper around Deep Agent.
    Handles invocation and automatic history persistence.
    """

    def __init__(
        self,
        agent_id: str,
        deep_agent,
        config: Dict,
        tenant_id: Optional[str] = None,
        token_tracker: Optional["TokenUsageTracker"] = None,
    ):
        """
        Initialize agent.

        Args:
            agent_id: Agent type identifier, as declared in config (e.g. "support-bot",
                "strategy_advisor"). Stays the same across tenants — see `tenant_id`.
            deep_agent: Configured Deep Agent instance
            config: Agent configuration dict
            tenant_id: Optional per-tenant scope (e.g. a workspace/customer id) for
                multi-tenant deployments where one `agent_id` must serve many
                independent tenants, each needing its own cache slot and its own
                conversation memory. Leave `None` for a single-tenant deployment
                (e.g. one Slack support bot) — behavior is then identical to before
                this parameter existed.
            token_tracker: Optional TokenUsageTracker instance for logging token usage
        """
        self.agent_id = agent_id
        self.tenant_id = tenant_id
        self._deep_agent = deep_agent
        self.config = config
        self.token_tracker = token_tracker

    @staticmethod
    def make_key(agent_id: str, tenant_id: Optional[str] = None) -> str:
        """Single source of truth for the (agent_id, tenant_id) composite identity.

        Used both as the `AgentFactory.agents_cache` key and as the thread_id
        namespace below. Callers that need to reference another tenant-scoped
        agent instance (e.g. building `allowed_agents` for delegation) must go
        through this instead of hand-formatting the string themselves — keeps
        the format defined in exactly one place.
        """
        return f"{agent_id}:{tenant_id}" if tenant_id else agent_id

    @property
    def instance_key(self) -> str:
        """This agent's own composite identity — see `make_key`."""
        return Agent.make_key(self.agent_id, self.tenant_id)

    def _format_todos(self, todos: List[Dict]) -> str:
        """
        Format todos for pretty printing.

        Args:
            todos: List of todo items

        Returns:
            Formatted string with todos
        """
        if not todos:
            return ""

        status_icons = {"pending": "⏳", "in_progress": "🔄", "completed": "✅"}

        lines = ["\n📝 Agent Todos:"]
        lines.append("─" * 60)

        for i, todo in enumerate(todos, 1):
            status = todo.get("status", "unknown")
            content = todo.get("content", "Unknown task")
            icon = status_icons.get(status, "❓")

            lines.append(f"{icon} [{i}] {content}")

        lines.append("─" * 60)
        return "\n".join(lines)

    def _format_tool_calls(self, messages: List) -> str:
        #### PRINTING TO DELETE
        """
        Format tool calls and their results for pretty printing.

        Args:
            messages: List of messages from the agent

        Returns:
            Formatted string with tool calls and results
        """
        lines = []
        tool_call_count = 0

        for msg in messages:
            # Check for thinking/reasoning first (from extended thinking)
            if hasattr(msg, "content"):
                content = msg.content
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "thinking":
                                thinking_text = block.get("thinking", "")
                                if thinking_text:
                                    lines.append(f"\n💭 Agent Thinking:")
                                    lines.append("─" * 60)
                                    # Split long thinking into multiple lines
                                    if len(thinking_text) > 400:
                                        lines.append(f"   {thinking_text[:400]}...")
                                    else:
                                        # Wrap text nicely
                                        for i in range(0, len(thinking_text), 80):
                                            lines.append(f"   {thinking_text[i:i+80]}")
                                    lines.append("─" * 60)

            # Check for tool calls (AI messages with tool_calls)
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    tool_call_count += 1
                    tool_name = tool_call.get("name", "unknown")
                    tool_args = tool_call.get("args", {})

                    lines.append(f"\n🔧 Tool Call #{tool_call_count}: {tool_name}")
                    lines.append("   Args:")
                    # Format args nicely
                    for key, value in tool_args.items():
                        if isinstance(value, str) and len(value) > 100:
                            lines.append(f"      {key}: {value[:100]}...")
                        else:
                            lines.append(f"      {key}: {value}")

            # Check for tool results (ToolMessage)
            if hasattr(msg, "type") and msg.type == "tool":
                tool_name = getattr(msg, "name", "unknown")
                content = getattr(msg, "content", "")

                # Try to parse JSON results
                import json

                try:
                    if isinstance(content, str):
                        parsed = json.loads(content)
                        if isinstance(parsed, dict):
                            lines.append(f"   ✓ Result:")
                            for key, value in parsed.items():
                                if isinstance(value, str) and len(value) > 100:
                                    lines.append(f"      {key}: {value[:100]}...")
                                else:
                                    lines.append(f"      {key}: {value}")
                        else:
                            lines.append(f"   ✓ Result: {str(parsed)[:200]}")
                    else:
                        # Truncate long content
                        if isinstance(content, str) and len(content) > 200:
                            content_preview = content[:200] + "..."
                        else:
                            content_preview = content
                        lines.append(f"   ✓ Result: {content_preview}")
                except:
                    # Not JSON, display as-is
                    if isinstance(content, str) and len(content) > 200:
                        content_preview = content[:200] + "..."
                    else:
                        content_preview = content
                    lines.append(f"   ✓ Result: {content_preview}")

        return "\n".join(lines) if lines else ""

    def _extract_tool_calls(self, messages: List) -> List[Dict[str, Any]]:
        """
        Extract structured tool call/result pairs from a turn's message list.

        `invoke()` only surfaced the final text reply — callers had no way to
        read a tool's return value (e.g. a tool that computes a structured
        side result meant for the caller, not for the model to restate).
        Matches each tool_call by id to its ToolMessage result.
        """
        calls_by_id: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        for msg in messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    tc_id = tool_call.get("id")
                    calls_by_id[tc_id] = {
                        "name": tool_call.get("name"),
                        "args": tool_call.get("args", {}),
                        "result": None,
                    }
                    order.append(tc_id)
            if hasattr(msg, "type") and msg.type == "tool":
                tc_id = getattr(msg, "tool_call_id", None)
                if tc_id in calls_by_id:
                    calls_by_id[tc_id]["result"] = getattr(msg, "content", None)
        return [calls_by_id[tc_id] for tc_id in order]

    async def _log_token_usage(self, user_id: str, thread_id: str, usage: Dict[str, Any]):
        """
        Log token usage to the token tracker.

        Args:
            user_id: User identifier
            thread_id: Thread identifier
            usage: Usage dict from LLM response (supports multiple formats)
        """
        if not self.token_tracker:
            return

        # Extract tokens from usage dict - support multiple formats
        # Anthropic/DeepAgents format: input_tokens, output_tokens
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")

        # OpenAI format: prompt_tokens, completion_tokens
        if input_tokens is None:
            input_tokens = usage.get("prompt_tokens")
        if output_tokens is None:
            output_tokens = usage.get("completion_tokens")

        # Ensure integers (handle None, string, float)
        try:
            input_tokens = int(input_tokens) if input_tokens is not None else 0
            output_tokens = int(output_tokens) if output_tokens is not None else 0
        except (ValueError, TypeError):
            logger.warning("Invalid token counts in usage: %s", usage)
            input_tokens = 0
            output_tokens = 0

        # Fallback: if total_tokens only, estimate split
        if input_tokens == 0 and output_tokens == 0:
            total_tokens = usage.get("total_tokens", 0)
            try:
                total_tokens = int(total_tokens)
            except (ValueError, TypeError):
                total_tokens = 0

            if total_tokens > 0:
                # Rough estimate: 70% input, 30% output (typical ratio)
                input_tokens = int(total_tokens * 0.7)
                output_tokens = int(total_tokens * 0.3)
                logger.warning(
                    "Usage contains only total_tokens=%d, estimating split: %d input, %d output",
                    total_tokens, input_tokens, output_tokens
                )

        if input_tokens == 0 and output_tokens == 0:
            # No usage to log
            logger.debug("No token usage found in result")
            return

        try:
            await self.token_tracker.log_usage(
                agent_id=self.agent_id,
                user_id=user_id,
                model=self.config.get("model", {}).get("name", "unknown"),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                tenant_id=self.tenant_id,
                thread_id=thread_id,
                metadata={
                    "agent_name": self.config.get("name"),
                    "model_provider": self.config.get("model", {}).get("provider"),
                },
            )
        except Exception as e:
            # Don't fail the request if token tracking fails
            logger.error("Failed to log token usage: %s", e, exc_info=True)

    async def _process_agent_response(self, user_id: str, input_data, message: str = "") -> Dict[str, Any]:
        """
        Internal method to process agent execution and handle interruptions.

        Args:
            user_id: User identifier
            input_data: Input data for agent (dict with messages, or Command for resume)
            message: User message (for logging)

        Returns:
            Dict with response and metadata
        """
        thread_id = f"{self.instance_key}-{user_id}"

        # Get recursion limit from config (default: 25)
        recursion_limit = self.config.get("recursion_limit", 25)

        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}

        if message:
            logger.info("User message: %s", message)
        logger.info("Processing with thread_id: %s", thread_id)

        # Start timing for metrics
        start_time = time.time()
        invocation_status = "success"

        # Invoke agent (blocks until done or interrupted)
        try:
            result = await self._deep_agent.ainvoke(input_data, config)
        except GraphRecursionError:
            invocation_status = "recursion_limit_exceeded"
            latency = time.time() - start_time

            # Record metrics
            if METRICS_ENABLED:
                record_invocation(self.agent_id, self.tenant_id, invocation_status, latency)
                recursion_limit_exceeded_total.labels(
                    agent_id=self.agent_id,
                    tenant_id=self.tenant_id or "none"
                ).inc()

            logger.error(
                "Agent exceeded maximum iterations (recursion_limit=%d, agent_id=%s, thread_id=%s)",
                recursion_limit, self.agent_id, thread_id
            )
            return {
                "agent_id": self.agent_id,
                "thread_id": thread_id,
                "response": f"Error: Agent exceeded maximum iterations ({recursion_limit}). This usually indicates an infinite loop.",
                "error": "recursion_limit_exceeded",
                "metadata": {"recursion_limit": recursion_limit, "latency": latency},
            }
        except Exception as e:
            invocation_status = "error"
            latency = time.time() - start_time

            # Record error metrics
            if METRICS_ENABLED:
                record_invocation(self.agent_id, self.tenant_id, invocation_status, latency)

            logger.exception(
                "Error during agent invocation (agent_id=%s, thread_id=%s, user_id=%s): %s",
                self.agent_id, thread_id, user_id, e
            )
            raise

        # Display tool calls and results
        if "messages" in result:
            tool_output = self._format_tool_calls(result["messages"])
            if tool_output:
                logger.info("\n%s\n%s\n%s", "═" * 60, tool_output, "═" * 60)

        # Display todos if present
        if "todos" in result and result["todos"]:
            logger.info(self._format_todos(result["todos"]))

        # Check if interrupted
        if "__interrupt__" in result:
            interrupts = result["__interrupt__"]

            # Extract action requests from the interrupt object
            if isinstance(interrupts, list) and len(interrupts) > 0:
                # DeepAgents returns a list of Interrupt objects
                interrupt_obj = interrupts[0]
                action_requests = interrupt_obj.value.get("action_requests", [])
            else:
                action_requests = []

            num_actions = len(action_requests)
            logger.info("INTERRUPTED - %d tool call(s) need approval", num_actions)

            # Collect decisions for each tool call
            decisions = []

            try:
                for i, action in enumerate(action_requests, 1):
                    tool_name = action.get("name", "unknown")
                    tool_args = action.get("args", {})

                    logger.info("[%d/%d] Tool: %s | Args: %s", i, num_actions, tool_name, tool_args)

                    # Ask for individual approval
                    user_input = input(f"   Approve this tool call? (y/n): ").strip().lower()
                    approve = user_input in ["y", "yes", "oui", "o"]

                    decision = {"type": "approve" if approve else "reject"}
                    decisions.append(decision)

                    logger.info("→ %s", "Approved" if approve else "Rejected")

                logger.info("Resuming with %d decision(s)...", len(decisions))

                # Resume with all decisions
                return await self._process_agent_response(
                    user_id=user_id, input_data=Command(resume={"decisions": decisions}), message=""
                )

            except (EOFError, KeyboardInterrupt):
                logger.info("Interrupted by user, rejecting all by default")
                decisions = [{"type": "reject"}] * num_actions
                return await self._process_agent_response(
                    user_id=user_id, input_data=Command(resume={"decisions": decisions}), message=""
                )

        # Extract final response
        last_message = result["messages"][-1]
        if hasattr(last_message, "content"):
            raw_content = last_message.content
        else:
            raw_content = last_message["content"]

        response_message = _extract_text(raw_content)

        # Display final tool calls and results
        if "messages" in result:
            tool_output = self._format_tool_calls(result["messages"])
            if tool_output:
                logger.info("\n%s\n%s\n%s", "═" * 60, tool_output, "═" * 60)

        # Display final todos if present
        if "todos" in result and result["todos"]:
            logger.info(self._format_todos(result["todos"]))

        logger.info(
            "Agent response: %s",
            response_message[:200] + "..." if len(response_message) > 200 else response_message,
        )

        # Log token usage if tracker is configured
        # Extract usage from last message (LangChain/DeepAgents format)
        usage = None
        if result and "messages" in result and result["messages"]:
            last_msg = result["messages"][-1]

            # Try usage_metadata first (standard LangChain format)
            if hasattr(last_msg, "usage_metadata") and last_msg.usage_metadata:
                usage = last_msg.usage_metadata
                logger.debug("Using usage_metadata from last message")

            # Fallback: try response_metadata.usage
            elif hasattr(last_msg, "response_metadata"):
                response_meta = last_msg.response_metadata
                if isinstance(response_meta, dict) and "usage" in response_meta:
                    usage = response_meta["usage"]
                    logger.debug("Using response_metadata.usage from last message")

        # Fallback: try result.get("usage") for older format
        if not usage and result:
            usage = result.get("usage")
            if usage:
                logger.debug("Using usage from result dict")
        if self.token_tracker and usage:
            logger.info("✅ Logging token usage to DB...")
            await self._log_token_usage(user_id, thread_id, usage)
            logger.debug("Token usage logged successfully")

        # Record Prometheus metrics (latency, tokens, cost)
        latency = time.time() - start_time
        if METRICS_ENABLED:
            # Record invocation metrics
            record_invocation(self.agent_id, self.tenant_id, invocation_status, latency)

            # Record token usage and cost metrics
            if usage and self.token_tracker:
                input_tokens = usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0)
                output_tokens = usage.get("output_tokens", 0) or usage.get("completion_tokens", 0)
                model_name = self.config.get("model", {}).get("name", "unknown")

                # Calculate cost using the token_tracker instance
                costs = self.token_tracker.calculate_cost(model_name, input_tokens, output_tokens)
                total_cost = float(costs["total_cost"])

                record_token_usage(
                    self.agent_id,
                    self.tenant_id,
                    model_name,
                    input_tokens,
                    output_tokens,
                    total_cost
                )

        return {
            "agent_id": self.agent_id,
            "tenant_id": self.tenant_id,
            "thread_id": thread_id,
            "response": response_message,
            "tool_calls": self._extract_tool_calls(result.get("messages", [])),
            "metadata": {
                "model": self.config.get("model", {}).get("name"),
                "usage": usage,
                "latency": latency,
            },
        }

    async def invoke(self, user_id: str, message: str, context: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Invoke agent with a message.

        History is automatically managed by Deep Agents via thread_id.

        Args:
            user_id: User identifier (for thread isolation)
            message: User message or event description
            context: Optional context metadata

        Returns:
            Dict with response and metadata
        """
        # Build message
        message_dict = {"role": "user", "content": message}
        if context:
            message_dict["metadata"] = context

        # Use shared processing method
        return await self._process_agent_response(
            user_id=user_id, input_data={"messages": [message_dict]}, message=message
        )

    async def stream_invoke(self, user_id: str, message: str, context: Optional[Dict] = None):
        """
        Invoke agent with streaming response.

        Yields events from the agent execution.
        """
        thread_id = f"{self.instance_key}-{user_id}"

        # Get recursion limit from config (default: 25)
        recursion_limit = self.config.get("recursion_limit", 25)

        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}

        message_dict = {"role": "user", "content": message}
        if context:
            message_dict["metadata"] = context

        logger.info("User message: %s", message)
        logger.info("Processing with thread_id: %s", thread_id)

        # Stream events
        async for event in self._deep_agent.astream_events({"messages": [message_dict]}, config):
            yield event

        # astream_events ne renvoie que des events bas niveau, pas le state final
        # (contrairement à ainvoke ci-dessus) — on relit l'état du graphe via le
        # checkpointer pour logger le même détail tool calls/todos que invoke().
        snapshot = await self._deep_agent.aget_state(config)
        messages = snapshot.values.get("messages", [])
        tool_output = self._format_tool_calls(messages)
        if tool_output:
            logger.info("\n%s\n%s\n%s", "═" * 60, tool_output, "═" * 60)

        todos = snapshot.values.get("todos")
        if todos:
            logger.info(self._format_todos(todos))

    async def get_history(self, user_id: str) -> List[Dict[str, str]]:
        """
        Return this thread's conversation as simple `{role, content}` turns, for display.

        Reads the graph's current state via the checkpointer instead of a separate
        history store — the checkpointer (keyed by `thread_id`) is already the single
        source of truth for conversation memory, so a caller displaying history to a
        user doesn't need a second, independently-maintained copy of it.

        Tool-call/tool-result messages (`ToolMessage`, or an `AIMessage` turn that
        only contains tool calls with no text) are omitted — they're implementation
        detail, not a conversational turn a user should see.
        """
        thread_id = f"{self.instance_key}-{user_id}"
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await self._deep_agent.aget_state(config)

        turns: List[Dict[str, str]] = []
        for msg in snapshot.values.get("messages", []):
            msg_type = getattr(msg, "type", None)
            if msg_type not in ("human", "ai"):
                continue
            text = _extract_text(getattr(msg, "content", None))
            if not text:
                continue
            turns.append({"role": "user" if msg_type == "human" else "assistant", "content": text})
        return turns

    async def clear_history(self, user_id: str) -> None:
        """Delete this thread's checkpointed state — resets the conversation."""
        thread_id = f"{self.instance_key}-{user_id}"
        checkpointer = self._deep_agent.checkpointer
        if checkpointer is not None:
            await checkpointer.adelete_thread(thread_id)

    def get_config(self) -> Dict:
        """Get agent configuration."""
        return self.config

    def get_tools(self) -> List[str]:
        """Get list of configured tool names."""
        return [tool.get("name") for tool in self.config.get("tools", [])]

    async def resume(self, user_id: str, approve: bool = True) -> Dict[str, Any]:
        """
        Resume execution after an interruption.

        Note: This method is kept for API compatibility but interruptions
        are now handled automatically inside _process_agent_response.

        Args:
            user_id: User identifier (to get correct thread)
            approve: True to approve and continue, False to reject

        Returns:
            Dict with response and metadata
        """
        decision_type = "approve" if approve else "reject"
        return await self._process_agent_response(
            user_id=user_id, input_data=Command(resume={"decisions": [{"type": decision_type}]}), message=""
        )
