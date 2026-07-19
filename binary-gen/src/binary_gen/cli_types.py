"""
Reusable Typer path argument/option presets and shared option type aliases.

Usage::

    from binary_gen.cli_types import READABLE_FILE, OUTPUT_FILE, PLATFORM_OPT

    path: Annotated[Path, typer.Argument(**READABLE_FILE, help="...")]
    output: Annotated[Path, typer.Option(**OUTPUT_FILE, "--output", "-o", help="...")]
    platform: PLATFORM_OPT = Platform.LINUX_X86
"""

from typing import Annotated, Any

import typer

from binary_gen.core import Platform

_RESOLVE: dict[str, Any] = {"resolve_path": True}
_EXISTING_READABLE: dict[str, Any] = {"exists": True, "readable": True}
_FILE: dict[str, Any] = {"file_okay": True, "dir_okay": False} | _RESOLVE
_DIR: dict[str, Any] = {"file_okay": False, "dir_okay": True} | _RESOLVE

EXISTING_PATH: dict[str, Any] = _EXISTING_READABLE | _RESOLVE  # file or dir

READABLE_FILE: dict[str, Any] = _FILE | _EXISTING_READABLE
WRITABLE_FILE: dict[str, Any] = _FILE | _EXISTING_READABLE | {"writable": True}

READABLE_DIR: dict[str, Any] = _DIR | _EXISTING_READABLE
WRITABLE_DIR: dict[str, Any] = _DIR | _EXISTING_READABLE | {"writable": True}

OUTPUT_FILE: dict[str, Any] = _FILE  # may not exist yet
OUTPUT_DIR: dict[str, Any] = _DIR  # may not exist yet

# ---------------------------------------------------------------------------
# Shared option type aliases
# ---------------------------------------------------------------------------

VERBOSE_OPT = Annotated[
    int,
    typer.Option(
        "-v",
        "--verbose",
        count=True,
        help="Increase verbosity: -v INFO, -vv project DEBUG, -vvv all DEBUG.",
    ),
]

# "Target platform architecture for the binary." — used on gen/run commands.
PLATFORM_OPT = Annotated[
    Platform,
    typer.Option("--platform", help="Target platform architecture for the binary."),
]

# "Target platform architecture to validate against." — used on check/eval commands.
PLATFORM_VALIDATE_OPT = Annotated[
    Platform,
    typer.Option("--platform", help="Target platform architecture to validate against."),
]

CLEAR_OPT = Annotated[
    bool,
    typer.Option(
        "--clear/--no-clear",
        help="Recursively delete the ENTIRE output directory before writing. This removes all subdirectories and files, not just the current mode.",
    ),
]

EXPECTED_STDOUT_OPT = Annotated[
    str,
    typer.Option(help="Expected stdout. Defaults to empty string (checks for no output)."),
]

EXPECTED_EXIT_OPT = Annotated[
    int,
    typer.Option(help="Expected exit code."),
]

HEX_OPT = Annotated[
    bool,
    typer.Option("--hex", help="Force hex interpretation (useful for hex files or stdin)."),
]

DUMP_HEX_OPT = Annotated[
    bool,
    typer.Option(help="Write a hex dump sidecar (.txt) next to the binary."),
]
