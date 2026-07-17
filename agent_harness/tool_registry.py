"""
Tool Registry - Central registry for all generic tools.
"""

import types
from typing import Dict, Callable, Any, Optional, Union, get_args, get_origin, Literal
from dataclasses import dataclass
from functools import partial
import inspect

from docstring_parser import parse as parse_docstring


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

    def _annotation_to_json_schema(self, annotation: Any) -> Dict[str, Any]:
        """
        Convert a Python type annotation to a JSON schema fragment.

        Handles the annotation shapes tools actually use: plain types, `Optional[X]`/
        `X | None`, `Literal[...]` (→ enum), and `list[X]`/`List[X]` (→ array + items).
        Anything unrecognized falls back to "string" rather than raising, since the
        LLM-facing schema should degrade gracefully instead of blocking registration.
        """
        origin = get_origin(annotation)

        # Optional[X] / X | None → unwrap to the non-None member
        if origin in (Union, types.UnionType):
            args = [a for a in get_args(annotation) if a is not type(None)]
            if len(args) == 1:
                return self._annotation_to_json_schema(args[0])
            # Multiple non-None members: no single JSON type fits, degrade to string.
            return {"type": "string"}

        if origin is Literal:
            values = get_args(annotation)
            value_type = type(values[0]) if values else str
            base = self._annotation_to_json_schema(value_type)
            base["enum"] = list(values)
            return base

        if origin in (list, tuple, set):
            item_args = get_args(annotation)
            items_schema = self._annotation_to_json_schema(item_args[0]) if item_args else {"type": "string"}
            return {"type": "array", "items": items_schema}

        type_map = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            dict: "object",
            list: "array",
        }
        return {"type": type_map.get(annotation, "string")}

    def _extract_schema(self, func: Callable) -> Dict[str, Any]:
        """
        Extract a JSON parameters schema from a function's signature and docstring.

        Per-parameter descriptions come from the docstring (Google/NumPy/ReST style,
        auto-detected) when present — this is what surfaces field-level guidance to
        the LLM (e.g. "onboarding_done: only true once every section is covered")
        without requiring tool authors to hand-write a JSON schema.
        """
        sig = inspect.signature(func)
        parsed_doc = parse_docstring(func.__doc__ or "")
        param_docs = {p.arg_name: p.description for p in parsed_doc.params if p.description}

        schema = {
            "type": "object",
            "properties": {},
            "required": []
        }

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue

            param_type = param.annotation if param.annotation != inspect.Parameter.empty else str
            prop_schema = self._annotation_to_json_schema(param_type)
            if param_name in param_docs:
                prop_schema["description"] = param_docs[param_name]

            schema["properties"][param_name] = prop_schema

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
