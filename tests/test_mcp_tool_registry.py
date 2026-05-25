import pytest

from src.mcp_tools.registry import McpToolRegistry, ToolDefinition, ToolValidationError


def test_registry_lists_registered_tool_schemas():
    registry = McpToolRegistry()
    registry.register(
        ToolDefinition(
            name="system.health",
            description="Return system health.",
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=lambda _: {"status": "healthy"},
        )
    )

    assert registry.list_tools() == [
        {
            "name": "system.health",
            "description": "Return system health.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
            "read_only": True,
        }
    ]


def test_registry_rejects_duplicate_tool_names():
    registry = McpToolRegistry()
    tool = ToolDefinition(
        name="portfolio.snapshot",
        description="Return portfolio snapshot.",
        input_schema={"type": "object", "properties": {}, "required": []},
        handler=lambda _: {},
    )

    registry.register(tool)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(tool)


def test_call_tool_validates_required_arguments_and_types():
    registry = McpToolRegistry()
    registry.register(
        ToolDefinition(
            name="events.replay",
            description="Replay recent events.",
            input_schema={
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
                "required": ["limit"],
            },
            handler=lambda args: {"limit": args["limit"]},
        )
    )

    assert registry.call_tool("events.replay", {"limit": 5}) == {"limit": 5}

    with pytest.raises(ToolValidationError, match="Missing required argument: limit"):
        registry.call_tool("events.replay", {})
    with pytest.raises(ToolValidationError, match="must be integer"):
        registry.call_tool("events.replay", {"limit": "5"})


def test_mutating_tools_are_blocked_unless_registry_allows_them():
    tool = ToolDefinition(
        name="orders.cancel",
        description="Cancel an order.",
        input_schema={
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
        handler=lambda args: {"cancelled": args["order_id"]},
        read_only=False,
    )
    readonly_registry = McpToolRegistry()
    readonly_registry.register(tool)

    with pytest.raises(PermissionError, match="Mutating tools are disabled"):
        readonly_registry.call_tool("orders.cancel", {"order_id": "OID-1"})

    mutating_registry = McpToolRegistry(allow_mutating=True)
    mutating_registry.register(tool)

    assert mutating_registry.call_tool("orders.cancel", {"order_id": "OID-1"}) == {
        "cancelled": "OID-1"
    }
