"""
Agent Wrapper - Wraps Deep Agent with invoke and history management.
"""

from typing import Dict, List, Any, Optional
from deepagents import create_deep_agent
from langgraph.types import Command
from langgraph.types import Command


class Agent:
    """
    Agent wrapper around Deep Agent.
    Handles invocation and automatic history persistence.
    """

    def __init__(self, agent_id: str, deep_agent, config: Dict):
        """
        Initialize agent.

        Args:
            agent_id: Unique agent identifier
            deep_agent: Configured Deep Agent instance
            config: Agent configuration dict
        """
        self.agent_id = agent_id
        self._deep_agent = deep_agent
        self.config = config

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
        thread_id = f"{self.agent_id}-{user_id}"
        config = {"configurable": {"thread_id": thread_id}}

        if message:
            print(f"\nUser message: {message}")
        print(f"Processing with thread_id: {thread_id}")

        # Invoke agent (blocks until done or interrupted)
        result = await self._deep_agent.ainvoke(input_data, config)

        # Display tool calls and results
        if "messages" in result:
            tool_output = self._format_tool_calls(result["messages"])
            if tool_output:
                print("\n" + "═" * 60)
                print(tool_output)
                print("═" * 60)

        # Display todos if present
        if "todos" in result and result["todos"]:
            print(self._format_todos(result["todos"]))

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
            print(f"\n⏸ INTERRUPTED - {num_actions} tool call(s) need approval")
            print("=" * 60)

            # Collect decisions for each tool call
            decisions = []

            try:
                for i, action in enumerate(action_requests, 1):
                    tool_name = action.get("name", "unknown")
                    tool_args = action.get("args", {})

                    print(f"\n[{i}/{num_actions}] Tool: {tool_name}")
                    print(f"   Args: {tool_args}")

                    # Ask for individual approval
                    user_input = input(f"   Approve this tool call? (y/n): ").strip().lower()
                    approve = user_input in ["y", "yes", "oui", "o"]

                    decision = {"type": "approve" if approve else "reject"}
                    decisions.append(decision)

                    print(f"   → {'✅ Approved' if approve else '❌ Rejected'}")

                print("\n" + "=" * 60)
                print(f"Resuming with {len(decisions)} decision(s)...")

                # Resume with all decisions
                return await self._process_agent_response(
                    user_id=user_id, input_data=Command(resume={"decisions": decisions}), message=""
                )

            except (EOFError, KeyboardInterrupt):
                print("\n   Interrupted by user, rejecting all by default")
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

        # Extract text from content. Content blocks aren't always [text] or
        # [text, ...] — extended thinking models commonly emit
        # [thinking, text] or end a tool-only turn with no text block at all
        # (e.g. a prompt instructing a "silent" tool call). Scanning by index
        # 0 alone misidentifies both cases; scan every block for text instead,
        # and fall back to "" (not "[]"/str(raw_content)) when none is found —
        # an empty turn is a legitimate outcome, not something to surface as
        # literal Python repr to the end user.
        if isinstance(raw_content, list):
            text_parts = [
                block.get("text", "")
                for block in raw_content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            response_message = "\n".join(part for part in text_parts if part)
        elif isinstance(raw_content, str):
            response_message = raw_content
        else:
            response_message = str(raw_content) if raw_content else ""

        # Display final tool calls and results
        if "messages" in result:
            tool_output = self._format_tool_calls(result["messages"])
            if tool_output:
                print("\n" + "═" * 60)
                print(tool_output)
                print("═" * 60)

        # Display final todos if present
        if "todos" in result and result["todos"]:
            print(self._format_todos(result["todos"]))

        print(
            f"\n🤖 Agent response: {response_message[:200]}..."
            if len(response_message) > 200
            else f"\n🤖 Agent response: {response_message}"
        )

        return {
            "agent_id": self.agent_id,
            "thread_id": thread_id,
            "response": response_message,
            "tool_calls": self._extract_tool_calls(result.get("messages", [])),
            "metadata": {
                "model": self.config.get("model", {}).get("name"),
                "usage": result.get("usage") if result else None,
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
        thread_id = f"{self.agent_id}-{user_id}"

        config = {"configurable": {"thread_id": thread_id}}

        message_dict = {"role": "user", "content": message}
        if context:
            message_dict["metadata"] = context

        # Stream events
        async for event in self._deep_agent.astream_events({"messages": [message_dict]}, config):
            yield event

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
