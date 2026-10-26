"""Supported target platforms and the `PlatformBuilder` protocol builders implement."""

import platform as _host  # stdlib; aliased to avoid clashing with this module's name
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import Protocol


class Platform(StrEnum):
    """Supported target platforms for code generation."""

    MAC_ARM = auto()
    LINUX_X86 = auto()

    @property
    def display_name(self) -> str:
        """Return a human-readable name for the platform (e.g. for logs and UI)."""
        match self:
            case Platform.MAC_ARM:
                return "macOS arm64"
            case Platform.LINUX_X86:
                return "Linux x86_64"
            case _:
                raise ValueError(f"No display name defined for {self!r}")


def host_platform() -> Platform | None:
    """Map the current host (OS + machine) to a Platform, or None if unsupported.

    The runner and `sign_binary` use this rather than their own `sys.platform`
    checks.
    """
    machine = _host.machine()

    if sys.platform == "darwin" and machine == "arm64":
        return Platform.MAC_ARM
    if sys.platform.startswith("linux") and machine == "x86_64":
        return Platform.LINUX_X86

    return None


def host_description() -> str:
    """Short host string for error messages, e.g. 'darwin/arm64'."""
    return f"{sys.platform}/{_host.machine()}"


def can_execute(target: Platform, *, use_docker: bool = False) -> bool:
    """Return True if a binary for ``target`` can be executed in this environment.

    Docker only covers Linux x86_64 (the runner's container is linux/amd64);
    everything else requires an exact host/target match.
    """
    if use_docker and target is Platform.LINUX_X86:
        return True

    return host_platform() is target


@dataclass
class DecodedInstruction:
    """One decoded instruction.

    Structured fields (``register``, ``immediate``) sit beside the display
    ``text`` so checks never parse strings.
    """

    offset: int  # file offset of the first byte
    size: int  # number of bytes consumed
    mnemonic: str  # e.g. "mov", "lea", "syscall", "movz", "adr", "svc"
    text: str  # human-readable display string
    register: str | None = None  # target register, if applicable
    immediate: int | None = None  # immediate / displacement value


#: Signature shared by all per-instruction decoders.
#:
#: Args:
#:     data: Byte slice starting at the candidate instruction.
#:     file_offset: Absolute file offset of ``data[0]``.
#:
#: Returns ``None`` when the bytes do not match this instruction pattern.
InstructionDecoder = Callable[[bytes, int], DecodedInstruction | None]


class PlatformBuilder(Protocol):
    """Protocol for platform-specific machine code builders.

    Implementations emit raw bytes that, when assembled into an executable
    for `platform`, perform the requested operation.
    """

    platform: Platform

    def build_print(self, s: str) -> bytes:
        """Emit machine code that writes `s` to standard output."""
        ...

    def build_exit(self, n: int) -> bytes:
        """Emit machine code that terminates the process with exit code `n`."""
        ...

    def build_print_exit(self, s: str, n: int) -> bytes:
        """Emit machine code that writes `s` to stdout then exits with code `n`."""
        ...
