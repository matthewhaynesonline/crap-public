"""
Command-line interface for Binary Gen.

Provides tools to generate, sign, evaluate, and inspect raw executable binaries.
"""

import logging
import subprocess
import sys
from functools import cache
from pathlib import Path
from typing import Annotated

import typer
from jinja2 import Environment, PackageLoader, Template

from binary_gen.cli_types import (
    DUMP_HEX_OPT,
    HEX_OPT,
    OUTPUT_FILE,
    PLATFORM_OPT,
    VERBOSE_OPT,
)
from binary_gen.cli_utils import configure_logging
from binary_gen.constants import DEFAULT_BIN_PATH, DEFAULT_MESSAGE
from binary_gen.core import (
    Platform,
    PlatformBuilder,
    get_builder,
    make_binary_executable,
    parse_hex,
    sign_binary,
)

# from binary_gen.core.analysis import analyze_binary, format_analysis
# from binary_gen.core.eval import eval_binary
from binary_gen.core.runner import run_binary

MAX_MESSAGE_LENGTH = 64

_RUN_DESCRIPTION = (
    "Linux binaries run in Docker (linux/amd64). macOS binaries execute "
    "natively and require a macOS ARM host."
)

logger = logging.getLogger(__name__)

app = typer.Typer(
    help="Binary Gen: Generate executable binaries from text messages.",
    add_completion=False,
)


@app.callback()
def _configure(
    verbose: VERBOSE_OPT = 0,
) -> None:
    """Configure logging based on the ``-v``/``-vv``/``-vvv`` flag count."""
    configure_logging(verbose)


def _validate_message(value: str) -> str:
    """Typer callback enforcing ASCII-only payloads within the byte-slot limit."""
    if not value.isascii():
        raise typer.BadParameter("Message must contain only ASCII characters.")

    if len(value) > MAX_MESSAGE_LENGTH:
        raise typer.BadParameter(f"Message must be {MAX_MESSAGE_LENGTH} characters or fewer.")

    return value


@app.command(name="gen")
def gen_cmd(
    message: Annotated[
        str,
        typer.Argument(
            help=f"The message to embed in the binary (max {MAX_MESSAGE_LENGTH} ASCII characters).",
            callback=_validate_message,
        ),
    ] = DEFAULT_MESSAGE,
    platform: PLATFORM_OPT = Platform.LINUX_X86,
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Output binary path.", **OUTPUT_FILE),
    ] = DEFAULT_BIN_PATH,
    jinja: Annotated[
        bool,
        typer.Option(
            help="For Mac: use Jinja template rendering instead of the raw binary builder."
        ),
    ] = False,
    run: Annotated[
        bool,
        typer.Option(
            help=f"Run the binary after building (similar to the 'run' command). {_RUN_DESCRIPTION}"
        ),
    ] = False,
    dump_hex: DUMP_HEX_OPT = True,
) -> None:
    """Generate an executable binary that prints `message` when run.

    Builds the binary for the target platform, writes it to `output`, applies
    the appropriate executable permissions (and code signature on macOS), and
    optionally executes it.
    """
    if jinja and platform is not Platform.MAC_ARM:
        raise typer.BadParameter("--jinja is only valid with --platform mac-arm")

    typer.secho("Starting build...", fg="cyan", bold=True)
    typer.echo(f"Payload: {message}")

    builder = get_builder(platform)

    if jinja:
        # Pad to MAX_MESSAGE_LENGTH to fill the fixed template slot. Characters
        # beyond the message become null bytes embedded in __cstring — the print
        # syscall uses the exact message length, so they are never written to stdout.
        padded_bytes = message.encode("ascii").ljust(MAX_MESSAGE_LENGTH, b"\x00")
        rendered = _get_binary_template().render(message_hex=padded_bytes.hex())

        try:
            binary_data = parse_hex(rendered)
        except ValueError as e:
            # The template is package-controlled, so this indicates a bug
            # rather than bad user input.
            typer.secho(
                f"Internal error: template produced invalid hex ({e}).",
                fg="red",
                bold=True,
            )

            raise typer.Exit(code=1) from None

    else:
        binary_data = builder.build_print(message)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(binary_data)

    _finalize_binary(output, builder)
    _dump_file_info(output, dump_hex=dump_hex)

    if run:
        _run_binary(binary_data, platform)

    typer.secho(f"\nSuccess! Wrote executable binary to {output}", fg="green", bold=True)


@app.command(name="run")
def run_cmd(
    source: Annotated[
        str,
        typer.Argument(
            help="Path to a binary or hex file, raw hex string, or '-' for stdin.",
        ),
    ] = str(DEFAULT_BIN_PATH),
    hex: HEX_OPT = False,
    platform: PLATFORM_OPT = Platform.LINUX_X86,
) -> None:
    """Execute a binary for the target platform.

    Linux binaries run in Docker (linux/amd64). macOS binaries execute
    natively and require a macOS ARM host.

    Auto-detects the input type: existing files are read as raw bytes,
    everything else is parsed as hex.  Use ``--hex`` to force hex
    interpretation (e.g. for a file containing hex text, or stdin).
    """
    binary_data = _parse_input_as_hex_or_exit(source) if hex else _read_binary_input(source)
    _run_binary(binary_data, platform)


@app.command(name="from-hex")
def from_hex_cmd(
    source: Annotated[
        str,
        typer.Argument(help="Raw hex string, path to a hex file, or '-' for stdin."),
    ],
    platform: PLATFORM_OPT = Platform.LINUX_X86,
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Output binary path.", **OUTPUT_FILE),
    ] = DEFAULT_BIN_PATH,
    dump_hex: DUMP_HEX_OPT = True,
    run: Annotated[
        bool,
        typer.Option(
            help=f"Run the binary after converting. {_RUN_DESCRIPTION}",
        ),
    ] = False,
) -> None:
    """Convert a raw hex string back into a runnable binary."""
    binary_data = _parse_input_as_hex_or_exit(source)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(binary_data)

    builder = get_builder(platform)
    _finalize_binary(output, builder)
    _dump_file_info(output, dump_hex=dump_hex)

    if run:
        _run_binary(binary_data, platform)

    typer.secho(f"\nSuccess! Wrote executable binary to {output}", fg="green", bold=True)


# @app.command(name="inspect")
# def inspect_cmd(
#     source: Annotated[
#         str,
#         typer.Argument(
#             help="Path to a binary or hex file, raw hex string, or '-' for stdin.",
#         ),
#     ],
#     hex: HEX_OPT = False,
# ) -> None:
#     """Inspect a binary's structure without executing it.

#     Parses the binary, auto-detects the target platform from magic bytes,
#     validates its format, decodes instructions, and reports any consistency
#     issues.

#     Auto-detects the input type: existing files are read as raw bytes,
#     everything else is parsed as hex.  Use ``--hex`` to force hex
#     interpretation (e.g. for a file containing hex text, or stdin).
#     """
#     binary_data = _parse_input_as_hex_or_exit(source) if hex else _read_binary_input(source)

#     analysis = analyze_binary(binary_data)
#     typer.echo(format_analysis(analysis))

#     if not analysis.valid:
#         raise typer.Exit(code=1)


# @app.command(name="eval")
# def eval_cmd(
#     source: Annotated[
#         str,
#         typer.Argument(
#             help="Path to a binary or hex file, raw hex string, or '-' for stdin.",
#         ),
#     ],
#     hex: HEX_OPT = False,
#     expected_stdout: EXPECTED_STDOUT_OPT = "",
#     expected_exit: EXPECTED_EXIT_OPT = 0,
#     platform: PLATFORM_VALIDATE_OPT = Platform.LINUX_X86,
# ) -> None:
#     """Evaluate a binary end-to-end.

#     Runs the full eval pipeline (hex → bytes → structural validation →
#     Docker/native execution), then compares stdout and exit code against
#     the expected values. Prints PASSED on success, or the full eval result
#     and FAILED (exit 1) on any mismatch.

#     Auto-detects the input type: existing files are read as raw bytes,
#     everything else is parsed as hex.  Use ``--hex`` to force hex
#     interpretation (e.g. for a file containing hex text, or stdin).
#     """
#     # eval_binary expects a hex string.  When reading a binary file,
#     # convert the raw bytes to hex so the eval pipeline's hex-decode
#     # stage still exercises the full round-trip.
#     if hex:
#         hex_data = _parse_text_input(source)
#     else:
#         binary_data = _read_binary_input(source)
#         hex_data = binary_data.hex()

#     eval_result = eval_binary(hex_data, platform, expected_stdout.encode(), expected_exit)

#     print_eval_result(eval_result)

#     if eval_result.passed:
#         typer.secho("PASSED", fg="green", bold=True)
#     else:
#         typer.secho("FAILED", fg="red", bold=True)
#         raise typer.Exit(code=1)


# ─────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────


def _parse_input_as_hex_or_exit(raw_input: str) -> bytes:
    """Resolve a CLI argument to a hex string (via file, stdin, or literal) then parse to bytes.

    Combines ``_parse_text_input`` (handles ``-``, file paths, and literals) with
    ``_parse_hex_or_exit`` (hex → bytes with a user-friendly error on failure).
    """
    return _parse_hex_or_exit(_parse_text_input(raw_input))


def _parse_text_input(raw_input: str) -> str:
    """Resolve a CLI argument that may be a literal string, a file path, or stdin ('-').

    Long hex payloads passed directly on the command line can exceed the
    OS's maximum path length; we treat any `OSError` from the `is_file`
    probe as "not a path" and fall through to returning the raw string.
    """
    if raw_input == "-":
        return sys.stdin.read()

    try:
        candidate = Path(raw_input)

        if candidate.is_file():
            return candidate.read_text()

    except OSError:
        pass

    return raw_input


def _parse_hex_or_exit(hex_data: str) -> bytes:
    """Parse a hex string into bytes, or exit with a user-friendly error."""
    try:
        return parse_hex(hex_data)
    except ValueError:
        typer.secho("Error: Invalid hex string.", fg="red", bold=True)
        raise typer.Exit(code=1) from None


def _read_binary_input(source: str) -> bytes:
    """Read source as raw bytes if it's a file, otherwise parse as hex."""
    if source == "-":
        return sys.stdin.buffer.read()

    try:
        path = Path(source)

        if path.is_file():
            return path.read_bytes()

    except OSError:
        pass

    return _parse_hex_or_exit(source)


@cache
def _get_binary_template() -> Template:
    """Load (and cache) the binary Jinja template from the package namespace."""
    env = Environment(loader=PackageLoader("binary_gen", "templates"))
    return env.get_template("bin.txt")


def _finalize_binary(output_path: Path, builder: PlatformBuilder) -> None:
    """Apply executable permissions and re-sign the binary (macOS only).

    macOS two-step signing: the Python builder embeds a placeholder code
    signature that establishes the correct LC_CODE_SIGNATURE layout and
    __LINKEDIT offsets, but is not accepted by the kernel for execution.
    The codesign call here replaces the placeholder with a cryptographically
    valid ad-hoc signature without restructuring the file. Both steps are
    required — Python sets up the layout, codesign makes it executable.

    Linux binaries need no signing; chmod is sufficient.
    """
    try:
        make_binary_executable(output_path)

        if builder.platform is Platform.MAC_ARM:
            sign_binary(output_path, builder.platform)

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        typer.secho(f"\nFailed to finalize binary: {e}", fg="red", bold=True)
        raise typer.Exit(code=1) from None


def _dump_file_info(output_path: Path, dump_hex: bool = True) -> None:
    """Print file type and size, and optionally dump a hex sidecar `.txt` file.

    Best-effort: missing system tools (`file`, `xxd`) emit a warning rather
    than aborting the command.
    """
    try:
        subprocess.run(["file", str(output_path)], check=True)
        typer.echo(f"Size: {output_path.stat().st_size} bytes")

        if dump_hex:
            txt_path = output_path.with_suffix(output_path.suffix + ".txt")

            with txt_path.open("w") as f:
                subprocess.run(["xxd", str(output_path)], stdout=f, check=True)

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.warning("Inspection tools unavailable: %s", e)


def _run_binary(binary_data: bytes, platform: Platform) -> None:
    """Run a binary blob for `platform` and print its stdout and (if nonzero) exit code."""
    result = run_binary(binary_data, platform)
    typer.echo(result.stdout.decode(errors="replace"), nl=False)

    if result.exit_code != 0:
        typer.secho(f"Exit code: {result.exit_code}", fg="yellow")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main() -> None:
    """Console script entry point. Wired up in pyproject.toml."""
    app()


if __name__ == "__main__":
    main()
