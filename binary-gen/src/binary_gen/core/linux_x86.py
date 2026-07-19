"""
Linux x86_64 binary builder.

Constructs minimal, statically-linked ELF executables directly from raw
instruction bytes - no assembler, linker, or libc required. Used to generate
ground-truth binaries for comparison against model-generated hex blobs.

Output is intentionally minimal: one PT_LOAD segment, no section headers,
no symbols, no relocations. Just enough for the Linux kernel to load and run.
"""

import struct

from binary_gen.core.platform import DecodedInstruction, InstructionDecoder, Platform

# ─────────────────────────────────────────────────────────
# ELF constants
# ─────────────────────────────────────────────────────────

# ELF magic bytes — shared with analysis.detect_platform (single source of truth).
ELF_MAGIC = b"\x7fELF"

# ELF file structure sizes
ELF_HEADER_SIZE = 64
PROGRAM_HEADER_SIZE = 56
SECTION_HEADER_SIZE = 64  # ELF64 section header size; we emit none but the
# field is conventionally set anyway

# e_ident byte values
EI_CLASS_64 = 2  # 64-bit objects
EI_DATA_LSB = 1  # little-endian
EI_OSABI_SYSV = 0  # System V ABI
EI_ABIVERSION = 0

# ELF header field values
ET_EXEC = 2  # e_type: executable file
EM_X86_64 = 0x3E  # e_machine: AMD x86-64
EV_CURRENT = 1  # e_version / EI_VERSION: current

# Program header field values
PT_LOAD = 1  # p_type: loadable segment
PF_X = 1  # p_flags: executable
PF_W = 2  # p_flags: writable
PF_R = 4  # p_flags: readable
PF_R_X = PF_R | PF_X  # 5
PAGE_ALIGN = 0x200000  # p_align: 2 MiB alignment (x86_64 large-page)

# Memory layout
LINUX_BASE = 0x400000
LINUX_CODE_OFFSET = ELF_HEADER_SIZE + PROGRAM_HEADER_SIZE  # 120 (0x78)

# ─────────────────────────────────────────────────────────
# Linux syscall numbers (x86_64 ABI)
# ─────────────────────────────────────────────────────────

SYS_WRITE = 1
SYS_EXIT = 60
STDOUT_FD = 1

# ─────────────────────────────────────────────────────────
# x86_64 instruction encoding / decoding
# ─────────────────────────────────────────────────────────

# Shared mapping — single source of truth for opcode ↔ register.
_REX_W = 0x48
_MOV_R64_OPCODES: dict[str, int] = {"rax": 0xB8, "rdi": 0xBF, "rdx": 0xBA}
_MOV_R64_REGS: dict[int, str] = {v: k for k, v in _MOV_R64_OPCODES.items()}
_MOV_R64_SIZE = 10  # REX.W(1) + opcode(1) + imm64(8)

_LEA_RSI_RIP_PREFIX = b"\x48\x8d\x35"
_LEA_RSI_RIP_SIZE = 7  # prefix(3) + disp32(4)

SYSCALL = b"\x0f\x05"
_SYSCALL_SIZE = 2


# ── Encoders ──────────────────────────────────────────────


def _x86_mov_r64(reg: str, imm: int) -> bytes:
    """Encode `REX.W mov r64, imm64`."""
    return bytes([_REX_W, _MOV_R64_OPCODES[reg]]) + struct.pack("<Q", imm)


def x86_mov_rax(imm: int) -> bytes:
    """Encode `REX.W mov rax, imm64`. `imm` must fit in an unsigned 64-bit word."""
    return _x86_mov_r64("rax", imm)


def x86_mov_rdi(imm: int) -> bytes:
    """Encode `REX.W mov rdi, imm64`. `imm` must fit in an unsigned 64-bit word."""
    return _x86_mov_r64("rdi", imm)


def x86_mov_rdx(imm: int) -> bytes:
    """Encode `REX.W mov rdx, imm64`. `imm` must fit in an unsigned 64-bit word."""
    return _x86_mov_r64("rdx", imm)


def x86_lea_rsi_rip(offset: int) -> bytes:
    """
    Encode `lea rsi, [rip + offset]`.

    The offset is a signed 32-bit displacement relative to the *next*
    instruction (i.e., RIP after this lea).

    Raises:
        ValueError: If `offset` is outside the signed 32-bit range.
    """
    if not (-(1 << 31) <= offset < (1 << 31)):
        raise ValueError(f"LEA offset {offset} out of signed 32-bit range")

    return _LEA_RSI_RIP_PREFIX + struct.pack("<i", offset)


# ── Decoders ──────────────────────────────────────────────


def _decode_mov_r64_imm64(data: bytes, file_offset: int) -> DecodedInstruction | None:
    """Decode `REX.W mov r64, imm64`."""
    if len(data) >= _MOV_R64_SIZE and data[0] == _REX_W and data[1] in _MOV_R64_REGS:
        reg = _MOV_R64_REGS[data[1]]
        imm = struct.unpack("<Q", data[2:10])[0]

        return DecodedInstruction(
            offset=file_offset,
            size=_MOV_R64_SIZE,
            mnemonic="mov",
            text=f"mov {reg}, {imm} (0x{imm:x})",
            register=reg,
            immediate=imm,
        )

    return None


def _decode_lea_rsi_rip(data: bytes, file_offset: int) -> DecodedInstruction | None:
    """Decode `lea rsi, [rip + disp32]`."""
    if len(data) >= _LEA_RSI_RIP_SIZE and data[:3] == _LEA_RSI_RIP_PREFIX:
        disp = struct.unpack("<i", data[3:7])[0]
        rip_after = file_offset + _LEA_RSI_RIP_SIZE
        target = rip_after + disp

        return DecodedInstruction(
            offset=file_offset,
            size=_LEA_RSI_RIP_SIZE,
            mnemonic="lea",
            text=f"lea rsi, [rip + {disp}] (target: file offset 0x{target:x})",
            register="rsi",
            immediate=disp,
        )

    return None


def _decode_syscall(data: bytes, file_offset: int) -> DecodedInstruction | None:
    """Decode `syscall`."""
    if len(data) >= _SYSCALL_SIZE and data[:2] == SYSCALL:
        return DecodedInstruction(
            offset=file_offset,
            size=_SYSCALL_SIZE,
            mnemonic="syscall",
            text="syscall",
        )

    return None


#: Ordered list of x86_64 instruction decoders for the analysis pipeline.
X86_DECODERS: list[InstructionDecoder] = [
    _decode_mov_r64_imm64,
    _decode_lea_rsi_rip,
    _decode_syscall,
]

# ─────────────────────────────────────────────────────────
# ELF binary builder
# ─────────────────────────────────────────────────────────

# linux_print uses a fixed instruction sequence. Layout:
#
#   offset  size  instruction
#   ──────  ────  ──────────────────────────────────
#       0    10   mov rax, SYS_WRITE
#      10    10   mov rdi, STDOUT_FD
#      20     7   lea rsi, [rip + 34]     <- RIP after = 27
#      27    10   mov rdx, len(data)
#      37     2   syscall
#      39    10   mov rax, SYS_EXIT
#      49    10   mov rdi, 0
#      59     2   syscall
#      61    --   <data starts here>
#
# lea offset = 61 (string start) - 27 (RIP after lea) = 34.
# This value is load-bearing and must stay in sync with the layout above.
_PRINT_CODE_SIZE = 10 + 10 + 7 + 10 + 2 + 10 + 10 + 2  # 61 bytes
_PRINT_LEA_RIP_OFFSET = 10 + 10 + 7  # 27 (RIP after lea)
_PRINT_LEA_RIP_TO_STRING = _PRINT_CODE_SIZE - _PRINT_LEA_RIP_OFFSET  # 34
assert _PRINT_LEA_RIP_TO_STRING == 34, "lea offset derivation changed - update x86_lea_rsi_rip call"

# No AMFI equivalent on Linux - purely static binaries run without codesigning.
#
# File layout (all offsets fixed):
#   0x00:                ELF header   (64 bytes)
#   0x40:                PT_LOAD phdr (56 bytes)
#   0x78:                <code>
#   0x78 + len(code):    <data>


def build_linux_binary(code: bytes, data: bytes = b"") -> bytes:
    """
    Build a raw static Linux x86_64 ELF binary from code and optional data.

    Produces a minimal executable: one PT_LOAD segment containing the code
    followed by the data, mapped at LINUX_BASE with read+execute permissions.
    No section headers, no symbols, no dynamic linking.

    Args:
        code: Raw x86_64 machine code. The entry point is the first byte.
        data: Optional bytes appended after the code (e.g., string literals
            referenced by RIP-relative loads in `code`).

    Returns:
        Complete ELF binary bytes, ready to be written to a file and executed.
    """
    payload = code + data
    total_size = LINUX_CODE_OFFSET + len(payload)
    entry = LINUX_BASE + LINUX_CODE_OFFSET

    # e_ident: magic(4) + EI_CLASS + EI_DATA + EI_VERSION + EI_OSABI
    #          + EI_ABIVERSION + 7 padding bytes  →  16 bytes total
    e_ident = (
        ELF_MAGIC
        + bytes([EI_CLASS_64, EI_DATA_LSB, EV_CURRENT, EI_OSABI_SYSV, EI_ABIVERSION])
        + bytes(7)
    )

    e_rest = struct.pack(
        "<HHIQQQIHHHHHH",
        ET_EXEC,
        EM_X86_64,
        EV_CURRENT,
        entry,
        ELF_HEADER_SIZE,  # e_phoff: program header table immediately follows ELF header
        0,  # e_shoff: no section header table
        0,  # e_flags
        ELF_HEADER_SIZE,  # e_ehsize
        PROGRAM_HEADER_SIZE,  # e_phentsize
        1,  # e_phnum: one program header
        SECTION_HEADER_SIZE,  # e_shentsize: unused (no section headers) but conventionally set
        0,  # e_shnum
        0,  # e_shstrndx
    )

    phdr = struct.pack(
        "<IIQQQQQQ",
        PT_LOAD,
        PF_R_X,
        0,  # p_offset: segment starts at the beginning of the file
        LINUX_BASE,  # p_vaddr
        LINUX_BASE,  # p_paddr
        total_size,  # p_filesz
        total_size,  # p_memsz
        PAGE_ALIGN,
    )

    return e_ident + e_rest + phdr + payload


# ─────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────


def linux_print(s: str) -> bytes:
    """
    Build a Linux x86_64 binary that writes `s` (with a trailing newline)
    to stdout and exits cleanly with code 0.

    Args:
        s: ASCII string to print. Non-ASCII characters raise UnicodeEncodeError.
    """
    data = s.encode("ascii") + b"\n"

    code = (
        x86_mov_rax(SYS_WRITE)
        + x86_mov_rdi(STDOUT_FD)
        + x86_lea_rsi_rip(_PRINT_LEA_RIP_TO_STRING)
        + x86_mov_rdx(len(data))
        + SYSCALL
        + x86_mov_rax(SYS_EXIT)
        + x86_mov_rdi(0)
        + SYSCALL
    )

    return build_linux_binary(code, data)


def linux_print_exit(s: str, n: int) -> bytes:
    """
    Build a Linux x86_64 binary that writes `s` (with a trailing newline)
    to stdout and exits with code `n`.

    Unlike `linux_print`, which always exits 0, this allows an arbitrary
    exit code — the only difference is the `mov rdi, n` before the exit
    syscall.

    Args:
        s: ASCII string to print.
        n: Exit status, 0–255.

    Raises:
        ValueError: If `n` is outside [0, 255].
    """
    if not (0 <= n <= 255):
        raise ValueError("Exit code must be between 0 and 255.")

    data = s.encode("ascii") + b"\n"

    code = (
        x86_mov_rax(SYS_WRITE)
        + x86_mov_rdi(STDOUT_FD)
        + x86_lea_rsi_rip(_PRINT_LEA_RIP_TO_STRING)
        + x86_mov_rdx(len(data))
        + SYSCALL
        + x86_mov_rax(SYS_EXIT)
        + x86_mov_rdi(n)
        + SYSCALL
    )

    return build_linux_binary(code, data)


def linux_exit(n: int) -> bytes:
    """
    Build a minimal Linux x86_64 binary that exits with status code `n`.

    Args:
        n: Exit status, 0–255.

    Raises:
        ValueError: If `n` is outside [0, 255].
    """
    if not (0 <= n <= 255):
        raise ValueError("Exit code must be between 0 and 255.")

    code = x86_mov_rax(SYS_EXIT) + x86_mov_rdi(n) + SYSCALL

    return build_linux_binary(code)


# ─────────────────────────────────────────────────────────
# Builder
# ─────────────────────────────────────────────────────────


class LinuxX86Builder:
    """Linux x86_64 implementation of the PlatformBuilder protocol."""

    platform = Platform.LINUX_X86

    def build_print(self, s: str) -> bytes:
        return linux_print(s)

    def build_exit(self, n: int) -> bytes:
        return linux_exit(n)

    def build_print_exit(self, s: str, n: int) -> bytes:
        return linux_print_exit(s, n)


builder = LinuxX86Builder()
