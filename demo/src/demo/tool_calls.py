"""Parse model tool calls without evaluating model-generated Python."""

import ast
import json
from dataclasses import dataclass
from typing import ClassVar

from binary_gen.core import Platform, get_builder

__all__ = ["BuildExit", "BuildPrint", "ToolCall", "build_tool_binary", "parse_tool_call"]


@dataclass(frozen=True)
class BuildPrint:
    """A literal ASCII payload, including empty and numeric strings."""

    name: ClassVar[str] = "build_print"
    message: str

    def __post_init__(self) -> None:
        if type(self.message) is not str or not self.message.isascii():
            raise ValueError("build_print requires an ASCII string message.")


@dataclass(frozen=True)
class BuildExit:
    """A normal process exit status, never a coerced float, bool, or string."""

    name: ClassVar[str] = "build_exit"
    exit_code: int

    def __post_init__(self) -> None:
        if type(self.exit_code) is not int or not 0 <= self.exit_code <= 255:
            raise ValueError("build_exit requires an integer exit_code between 0 and 255.")


type ToolCall = BuildPrint | BuildExit
type _JsonValue = None | bool | int | float | str | list[_JsonValue] | dict[str, _JsonValue]


def parse_tool_call(response: str) -> ToolCall:
    """Accept one JSON object (or singleton list), or a literal keyword call.

    JSON accepts ``arguments`` or the legacy ``args`` key. Python syntax must
    be exactly ``build_print(message=...)`` or ``build_exit(exit_code=...)``;
    expressions, positional arguments, duplicate keys and extra calls fail.

    Raises:
        ValueError: The response does not contain one complete, valid call.
    """
    try:
        data: _JsonValue = json.loads(response, object_pairs_hook=_unique_object)
    except json.JSONDecodeError:
        name, arguments = _parse_literal_call(response)
    else:
        if isinstance(data, list) and len(data) == 1:
            data = data[0]
        if not isinstance(data, dict):
            raise ValueError("Expected one tool-call object.")
        argument_keys = set(data) & {"arguments", "args"}
        if len(argument_keys) != 1 or set(data) != {"name", *argument_keys}:
            raise ValueError("Expected name and exactly one arguments object.")
        name = data["name"]
        arguments = data[argument_keys.pop()]

    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object.")
    if name == "build_print" and set(arguments) == {"message"}:
        message = arguments["message"]
        if not isinstance(message, str):
            raise ValueError("build_print requires an ASCII string message.")

        return BuildPrint(message)
    if name == "build_exit" and set(arguments) == {"exit_code"}:
        exit_code = arguments["exit_code"]
        if type(exit_code) is not int:
            raise ValueError("build_exit requires an integer exit_code between 0 and 255.")

        return BuildExit(exit_code)

    raise ValueError("Expected build_print(message=...) or build_exit(exit_code=...).")


def build_tool_binary(call: ToolCall) -> bytes:
    """Build Linux x86_64 bytes from a validated call, without executing them."""
    builder = get_builder(Platform.LINUX_X86)
    match call:
        case BuildPrint(message=message):
            return builder.build_print(message)
        case BuildExit(exit_code=exit_code):
            return builder.build_exit(exit_code)


def _parse_literal_call(response: str) -> tuple[str, dict[str, object]]:
    try:
        expression = ast.parse(response.strip(), mode="eval").body
    except (SyntaxError, ValueError) as error:
        raise ValueError("Expected JSON or a literal tool call.") from error
    if not isinstance(expression, ast.Call) or not isinstance(expression.func, ast.Name):
        raise ValueError("Expected a named tool call.")
    if expression.args:
        raise ValueError("Tool arguments must be named.")

    arguments: dict[str, object] = {}
    for keyword in expression.keywords:
        if keyword.arg is None or keyword.arg in arguments:
            raise ValueError("Expanded or duplicate tool arguments are not supported.")
        try:
            arguments[keyword.arg] = ast.literal_eval(keyword.value)
        except (ValueError, TypeError) as error:
            raise ValueError("Tool arguments must be literal values.") from error

    return expression.func.id, arguments


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value

    return result
