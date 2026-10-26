import json

import pytest
from demo.tool_calls import BuildExit, BuildPrint, build_tool_binary, parse_tool_call


@pytest.mark.parametrize("message", ["", "123", 'a "quote" and ) bracket', "%s%n", "line\nbreak"])
def test_print_strings_preserved(message: str) -> None:
    for response in (
        json.dumps({"name": "build_print", "arguments": {"message": message}}),
        f"build_print(message={message!r})",
    ):
        call = parse_tool_call(response)
        assert call == BuildPrint(message)
        assert build_tool_binary(call).endswith(message.encode("ascii") + b"\n")


@pytest.mark.parametrize("code", [0, 42, 139, 255])
def test_exit_arguments(code: int) -> None:
    call = parse_tool_call(f"build_exit(exit_code={code})")
    assert call == BuildExit(code)
    assert build_tool_binary(call).startswith(b"\x7fELF")


@pytest.mark.parametrize(
    "response",
    [
        "build_print(message=123)",
        "build_print(message=None)",
        "build_print()",
        'build_print(message="é")',
        "build_exit(exit_code=True)",
        "build_exit(exit_code=False)",
        "build_exit(exit_code=1.5)",
        'build_exit(exit_code="42")',
        "build_exit(exit_code=-1)",
        "build_exit(exit_code=256)",
        "build_exit()",
        "build_exit(42)",
        "build_exit(exit_code=1+1)",
        "build_exit(exit_code=1, exit_code=2)",
        'build_exit(**{"exit_code": 1})',
        "build_exit(exit_code=0); build_exit(exit_code=1)",
        "prefix build_exit(exit_code=0)",
        "unknown(exit_code=0)",
        '{"name": "build_print", "arguments": []}',
        '{"name": "build_print", "arguments": null}',
        '{"name": "build_print", "arguments": {"message": "", "extra": 0}}',
        '{"name": "build_exit", "arguments": {"exit_code": true}}',
        '{"name": "build_exit", "arguments": {}, "args": {}}',
        '{"name": "build_exit"}',
        "{bad json}",
        "[]",
        "[{}, {}]",
        '"hello"',
    ],
)
def test_invalid_tool_calls(response: str) -> None:
    with pytest.raises(ValueError, match="."):
        parse_tool_call(response)


def test_legacy_singleton_and_args() -> None:
    assert parse_tool_call('[{"name":"build_print","args":{"message":""}}]') == BuildPrint("")


def test_duplicate_json_keys_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        parse_tool_call('{"name":"build_exit","arguments":{"exit_code":0,"exit_code":1}}')
