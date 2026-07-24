"""Unit tests for agent_harness.tool_registry.ToolRegistry."""

from typing import List, Literal, Optional

import pytest

from agent_harness.tool_registry import ToolDefinition, ToolRegistry


@pytest.fixture
def registry() -> ToolRegistry:
    """A fresh registry per test — never share the global singleton."""
    return ToolRegistry()


# --------------------------------------------------------------------------
# register()
# --------------------------------------------------------------------------


class TestRegister:
    def test_register_as_decorator_uses_function_name_and_docstring(self, registry):
        @registry.register()
        def my_tool(x: str) -> str:
            """Do a thing."""
            return x

        tool_def = registry.get("my_tool")
        assert tool_def is not None
        assert tool_def.name == "my_tool"
        assert tool_def.description == "Do a thing."
        assert tool_def.category == "general"
        assert tool_def.function is my_tool

    def test_register_with_custom_name_and_category(self, registry):
        @registry.register(category="api", name="renamed_tool")
        def original_name(x: str) -> str:
            return x

        assert registry.get("renamed_tool") is not None
        assert registry.get("original_name") is None
        assert registry.get("renamed_tool").category == "api"

    def test_register_direct_call_without_decorator_syntax(self, registry):
        def plain_func(x: str) -> str:
            return x

        result = registry.register(plain_func)

        # Direct-call form returns the function itself, like the decorator form.
        assert result is plain_func
        assert registry.get("plain_func") is not None

    def test_register_missing_docstring_yields_empty_description(self, registry):
        @registry.register()
        def undocumented(x: str) -> str:
            return x

        assert registry.get("undocumented").description == ""

    def test_register_overwrites_existing_name(self, registry):
        @registry.register(name="dup")
        def first(x: str) -> str:
            return x

        @registry.register(name="dup")
        def second(x: str) -> str:
            return x

        assert registry.get("dup").function is second


# --------------------------------------------------------------------------
# _annotation_to_json_schema / _extract_schema (via register())
# --------------------------------------------------------------------------


class TestSchemaExtraction:
    def test_plain_types(self, registry):
        @registry.register()
        def tool(a: str, b: int, c: float, d: bool, e: dict, f: list) -> None:
            pass

        props = registry.get("tool").parameters_schema["properties"]
        assert props["a"]["type"] == "string"
        assert props["b"]["type"] == "integer"
        assert props["c"]["type"] == "number"
        assert props["d"]["type"] == "boolean"
        assert props["e"]["type"] == "object"
        assert props["f"]["type"] == "array"

    def test_unrecognized_type_falls_back_to_string(self, registry):
        class Custom:
            pass

        @registry.register()
        def tool(a: Custom) -> None:
            pass

        assert registry.get("tool").parameters_schema["properties"]["a"]["type"] == "string"

    def test_optional_unwraps_to_inner_type(self, registry):
        @registry.register()
        def tool(a: Optional[int] = None) -> None:
            pass

        assert registry.get("tool").parameters_schema["properties"]["a"]["type"] == "integer"

    def test_union_of_multiple_non_none_types_degrades_to_string(self, registry):
        @registry.register()
        def tool(a: "int | str" = None) -> None:
            pass

        assert registry.get("tool").parameters_schema["properties"]["a"]["type"] == "string"

    def test_literal_becomes_enum(self, registry):
        @registry.register()
        def tool(mode: Literal["read", "write"] = "read") -> None:
            pass

        prop = registry.get("tool").parameters_schema["properties"]["mode"]
        assert prop["type"] == "string"
        assert prop["enum"] == ["read", "write"]

    def test_list_of_str_has_items_schema(self, registry):
        @registry.register()
        def tool(items: List[str]) -> None:
            pass

        prop = registry.get("tool").parameters_schema["properties"]["items"]
        assert prop["type"] == "array"
        assert prop["items"] == {"type": "string"}

    def test_bare_list_without_type_args_defaults_items_to_string(self, registry):
        @registry.register()
        def tool(items: list) -> None:
            pass

        prop = registry.get("tool").parameters_schema["properties"]["items"]
        assert prop["type"] == "array"

    def test_required_vs_default_params(self, registry):
        @registry.register()
        def tool(required_arg: str, optional_arg: str = "default") -> None:
            pass

        schema = registry.get("tool").parameters_schema
        assert schema["required"] == ["required_arg"]
        assert "optional_arg" not in schema["required"]

    def test_self_and_cls_are_skipped(self, registry):
        class Foo:
            def method(self, a: str) -> None:
                pass

        registry.register()(Foo.method)
        schema = registry.get("method").parameters_schema
        assert "self" not in schema["properties"]
        assert schema["required"] == ["a"]

    def test_param_description_pulled_from_google_style_docstring(self, registry):
        @registry.register()
        def tool(name: str) -> None:
            """Greet someone.

            Args:
                name: The person's name.
            """

        prop = registry.get("tool").parameters_schema["properties"]["name"]
        assert prop["description"] == "The person's name."

    def test_param_without_docstring_entry_has_no_description_key(self, registry):
        @registry.register()
        def tool(name: str) -> None:
            """Greet someone."""

        prop = registry.get("tool").parameters_schema["properties"]["name"]
        assert "description" not in prop

    def test_string_forward_ref_annotation_still_resolves(self, registry):
        @registry.register()
        def tool(mode: "Literal['a', 'b']" = "a") -> None:
            pass

        prop = registry.get("tool").parameters_schema["properties"]["mode"]
        assert prop.get("enum") == ["a", "b"]

    def test_unresolvable_forward_ref_falls_back_to_string(self, registry):
        # get_type_hints() raises NameError for a string annotation that
        # references a name not in the function's globals — the schema
        # extractor must degrade to "string" rather than propagate the error.
        def tool(a: "SomeUndefinedType") -> None:
            pass

        registry.register()(tool)
        assert registry.get("tool").parameters_schema["properties"]["a"]["type"] == "string"


# --------------------------------------------------------------------------
# get / list_by_category / list_all
# --------------------------------------------------------------------------


class TestLookup:
    def test_get_unknown_returns_none(self, registry):
        assert registry.get("does-not-exist") is None

    def test_list_by_category_filters(self, registry):
        @registry.register(category="api")
        def a_tool(x: str) -> None:
            pass

        @registry.register(category="db")
        def b_tool(x: str) -> None:
            pass

        api_tools = registry.list_by_category("api")
        assert [t.name for t in api_tools] == ["a_tool"]

    def test_list_all_returns_every_registered_tool(self, registry):
        @registry.register()
        def a(x: str) -> None:
            pass

        @registry.register()
        def b(x: str) -> None:
            pass

        names = {t.name for t in registry.list_all()}
        assert names == {"a", "b"}
        assert all(isinstance(t, ToolDefinition) for t in registry.list_all())


# --------------------------------------------------------------------------
# configure_tool()
# --------------------------------------------------------------------------


class TestConfigureTool:
    def test_unknown_tool_raises(self, registry):
        with pytest.raises(ValueError, match="not found in registry"):
            registry.configure_tool("nope", {})

    def test_sync_tool_config_is_prefilled(self, registry):
        @registry.register()
        def query(connection_string: str, sql: str) -> str:
            return f"{connection_string}:{sql}"

        configured = registry.configure_tool("query", {"connection_string": "sqlite:///x"})
        assert configured(sql="SELECT 1") == "sqlite:///x:SELECT 1"

    def test_runtime_kwargs_override_config(self, registry):
        @registry.register()
        def query(connection_string: str) -> str:
            return connection_string

        configured = registry.configure_tool("query", {"connection_string": "preset"})
        # merged_kwargs = {**config, **kwargs} -> explicit call-time kwargs win.
        assert configured(connection_string="override") == "override"

    @pytest.mark.asyncio
    async def test_async_tool_is_wrapped_and_awaited(self, registry):
        @registry.register()
        async def fetch(url: str) -> str:
            return f"fetched:{url}"

        configured = registry.configure_tool("fetch", {})
        result = await configured(url="http://x")
        assert result == "fetched:http://x"

    def test_rename_as_sets_wrapper_name(self, registry):
        @registry.register()
        def tool(x: str) -> str:
            return x

        configured = registry.configure_tool("tool", {}, rename_as="custom_name")
        assert configured.__name__ == "custom_name"

    def test_default_name_when_no_rename(self, registry):
        @registry.register()
        def tool(x: str) -> str:
            return x

        configured = registry.configure_tool("tool", {})
        assert configured.__name__ == "tool_configured"

    def test_wrapper_docstring_matches_original_description(self, registry):
        @registry.register()
        def tool(x: str) -> str:
            """Original description."""
            return x

        configured = registry.configure_tool("tool", {})
        assert configured.__doc__ == "Original description."

    def test_wrapper_signature_excludes_configured_params(self, registry):
        import inspect

        @registry.register()
        def tool(a: str, b: int) -> str:
            return f"{a}{b}"

        configured = registry.configure_tool("tool", {"a": "preset"})
        sig = inspect.signature(configured)
        assert list(sig.parameters) == ["b"]

    def test_wrapper_annotations_exclude_configured_params_but_keep_return(self, registry):
        @registry.register()
        def tool(a: str, b: int) -> bool:
            return True

        configured = registry.configure_tool("tool", {"a": "preset"})
        assert "a" not in configured.__annotations__
        assert configured.__annotations__["b"] is int
        assert configured.__annotations__["return"] is bool

    def test_empty_config_preserves_all_params(self, registry):
        import inspect

        @registry.register()
        def tool(a: str, b: int = 5) -> str:
            return a

        configured = registry.configure_tool("tool", {})
        sig = inspect.signature(configured)
        assert list(sig.parameters) == ["a", "b"]
