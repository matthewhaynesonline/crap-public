import re
import subprocess
from pathlib import Path

import lief

from binary_gen.core.linux_x86 import builder as linux_builder
from binary_gen.core.mac_arm import builder as mac_builder
from binary_gen.core.platform import (
    Platform,
    PlatformBuilder,
    host_description,
    host_platform,
)

# Suppress lief warnings once at import time. Our intentionally minimal binaries
# (no section headers on Linux, no symbols, etc.) trigger lief warnings that are
# expected and do not indicate failures.
lief.logging.disable()

BUILDERS: dict[Platform, PlatformBuilder] = {
    Platform.MAC_ARM: mac_builder,
    Platform.LINUX_X86: linux_builder,
}


def get_builder(platform: Platform) -> PlatformBuilder:
    """Returns the builder module for the given target platform."""
    return BUILDERS[platform]


def sign_binary(binary_path: Path, platform: Platform, quiet: bool = True) -> None:
    """
    Applies an ad-hoc codesignature to the binary using the system `codesign` tool.

    Only supported when targeting Mac ARM on a macOS host. Raises RuntimeError
    if the target platform or host platform doesn't support codesigning.

    Args:
        binary_path: Path to the binary to sign in place.
        platform: Target platform of the binary.
        quiet: If True, suppress codesign's stdout/stderr.
    """
    if platform is not Platform.MAC_ARM:
        raise RuntimeError(
            f"Target platform '{platform}' does not support codesign; "
            f"codesign is only supported on {Platform.MAC_ARM}."
        )

    if host_platform() is not Platform.MAC_ARM:
        raise RuntimeError(f"Host platform '{host_description()}' does not support codesign.")

    subprocess.run(
        ["codesign", "--force", "--sign", "-", str(binary_path)],
        check=True,
        capture_output=quiet,
    )


def make_binary_executable(binary_path: Path) -> None:
    """
    Adds the executable bit for user/group/other on the given file,
    preserving existing read/write permissions.
    """
    current_mode = binary_path.stat().st_mode
    binary_path.chmod(current_mode | 0o111)


def parse_hex(hex_data: str) -> bytes:
    """
    Parses a hex string into bytes. Whitespace is stripped before parsing.

    Raises ValueError on invalid input, preserving the underlying error's
    position information from bytes.fromhex().
    """
    clean_hex = _format_hex(hex_data)

    try:
        return bytes.fromhex(clean_hex)
    except ValueError as e:
        raise ValueError(f"Invalid hex: {e}") from e


def _format_hex(hex_data: str) -> str:
    """Strips all whitespace from a raw hex string."""
    return re.sub(r"\s+", "", hex_data)
