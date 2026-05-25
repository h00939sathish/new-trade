from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class ToolValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]
    read_only: bool = True


class McpToolRegistry:
    def __init__(self, allow_mutating: bool = False):
        self.allow_mutating = allow_mutating
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
                "read_only": tool.read_only,
            }
            for tool in self._tools.values()
        ]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        if name not in self._tools:
            raise KeyError(f"Tool not registered: {name}")
        tool = self._tools[name]
        if not tool.read_only and not self.allow_mutating:
            raise PermissionError("Mutating tools are disabled")
        args = arguments or {}
        self._validate(tool.input_schema, args)
        return tool.handler(args)

    def _validate(self, schema: dict[str, Any], arguments: dict[str, Any]) -> None:
        if schema.get("type") != "object":
            raise ToolValidationError("Tool input schema must be an object")

        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in arguments:
                raise ToolValidationError(f"Missing required argument: {key}")

        for key, value in arguments.items():
            expected = properties.get(key, {}).get("type")
            if expected is None:
                continue
            if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
                raise ToolValidationError(f"Argument {key} must be integer")
            if expected == "number" and (
                not isinstance(value, int | float) or isinstance(value, bool)
            ):
                raise ToolValidationError(f"Argument {key} must be number")
            if expected == "string" and not isinstance(value, str):
                raise ToolValidationError(f"Argument {key} must be string")
            if expected == "boolean" and not isinstance(value, bool):
                raise ToolValidationError(f"Argument {key} must be boolean")
            if expected == "object" and not isinstance(value, dict):
                raise ToolValidationError(f"Argument {key} must be object")
            if expected == "array" and not isinstance(value, list):
                raise ToolValidationError(f"Argument {key} must be array")
