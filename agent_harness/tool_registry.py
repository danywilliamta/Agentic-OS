"""
Tool Registry - Central registry for all generic tools.
"""

from typing import Dict, Callable, Any, Optional
from dataclasses import dataclass
from functools import partial
import inspect


@dataclass
class ToolDefinition:
    """Tool definition in registry."""
    name: str
    function: Callable
    description: str
    category: str
    parameters_schema: Dict[str, Any]


class ToolRegistry:
    """
    Central registry for all available tools.
    Tools are generic and configured via parameters.
    """

    def __init__(self):
        self.tools: Dict[str, ToolDefinition] = {}

    def register(
        self,
        func: Optional[Callable] = None,
        *,
        category: str = "general",
        name: Optional[str] = None
    ):
        """
        Register a tool (can be used as decorator).

        Usage:
            @tool_registry.register(category="api")
            def my_tool(...):
                pass
        """
        def decorator(f: Callable) -> Callable:
            tool_name = name or f.__name__

            tool_def = ToolDefinition(
                name=tool_name,
                function=f,
                description=f.__doc__ or "",
                category=category,
                parameters_schema=self._extract_schema(f)
            )

            self.tools[tool_name] = tool_def
            return f

        if func is None:
            return decorator
        else:
            return decorator(func)

    def _extract_schema(self, func: Callable) -> Dict[str, Any]:
        """Extract parameters schema from function signature."""
        sig = inspect.signature(func)
        schema = {
            "type": "object",
            "properties": {},
            "required": []
        }

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue

            param_type = param.annotation if param.annotation != inspect.Parameter.empty else str

            # Map Python types to JSON schema types
            type_map = {
                str: "string",
                int: "integer",
                float: "number",
                bool: "boolean",
                dict: "object",
                list: "array",
            }

            schema["properties"][param_name] = {
                "type": type_map.get(param_type, "string")
            }

            if param.default == inspect.Parameter.empty:
                schema["required"].append(param_name)

        return schema

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Get tool definition by name."""
        return self.tools.get(name)

    def list_by_category(self, category: str) -> list[ToolDefinition]:
        """List tools in a category."""
        return [t for t in self.tools.values() if t.category == category]

    def list_all(self) -> list[ToolDefinition]:
        """List all tools."""
        return list(self.tools.values())

    def configure_tool(
        self,
        tool_name: str,
        config: Dict[str, Any],
        rename_as: Optional[str] = None
    ) -> Callable:
        """
        Configure a generic tool with specific parameters.

        Args:
            tool_name: Name of generic tool in registry
            config: Configuration dict (preset parameters)
            rename_as: Optional new name for configured tool

        Returns:
            Configured callable function
        """
        tool_def = self.get(tool_name)
        if not tool_def:
            raise ValueError(f"Tool '{tool_name}' not found in registry")

        # Get original function signature
        sig = inspect.signature(tool_def.function)

        # Create new parameters excluding configured ones
        new_params = [
            param for name, param in sig.parameters.items()
            if name not in config
        ]

        # Create wrapper function with correct signature
        # Check if the original function is async
        if inspect.iscoroutinefunction(tool_def.function):
            # Create async wrapper
            async def wrapper(*args, **kwargs):
                # Merge config with runtime kwargs
                merged_kwargs = {**config, **kwargs}
                return await tool_def.function(*args, **merged_kwargs)
        else:
            # Create sync wrapper
            def wrapper(*args, **kwargs):
                # Merge config with runtime kwargs
                merged_kwargs = {**config, **kwargs}
                return tool_def.function(*args, **merged_kwargs)

        # Set proper signature for the wrapper
        wrapper.__signature__ = sig.replace(parameters=new_params)
        wrapper.__name__ = rename_as or f"{tool_name}_configured"
        wrapper.__doc__ = tool_def.description
        wrapper.__annotations__ = {
            name: param.annotation
            for name, param in sig.parameters.items()
            if name not in config
        }
        # Add return annotation if exists
        if sig.return_annotation != inspect.Signature.empty:
            wrapper.__annotations__['return'] = sig.return_annotation

        return wrapper


# Global registry instance
tool_registry = ToolRegistry()
