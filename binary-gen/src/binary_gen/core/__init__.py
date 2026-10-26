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

# The deliberately minimal binaries (no section headers, no symbols) make lief
# warn on every parse; those warnings aren't failures.
lief.logging.disable()

BUILDERS: dict[Platform, PlatformBuilder] = {
    Platform.MAC_ARM: mac_builder,
    Platform.LINUX_X86: linux_builder,
}


def get_builder(platform: Platform) -> PlatformBuilder:
    """Return the builder for `platform`."""
    return BUILDERS[platform]


def sign_binary(binary_path: Path, platform: Platform, quiet: bool = True) -> None:
    """
    Ad-hoc sign the binary in place with the system `codesign` tool.

    Raises RuntimeError unless both the target and the host are macOS arm64.

    Args:
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
    """Add the executable bit for user, group and other, keeping other permissions."""
    current_mode = binary_path.stat().st_mode
    binary_path.chmod(current_mode | 0o111)


def parse_hex(hex_data: str) -> bytes:
    """
    Strip whitespace, then decode. Raises ValueError on invalid input, keeping
    the position information from `bytes.fromhex()`.
    """
    clean_hex = _format_hex(hex_data)

    try:
        return bytes.fromhex(clean_hex)
    except ValueError as e:
        raise ValueError(f"Invalid hex: {e}") from e


def _format_hex(hex_data: str) -> str:
    return re.sub(r"\s+", "", hex_data)
