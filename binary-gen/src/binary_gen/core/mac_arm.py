"""
Raw Mach-O (macOS arm64) binary builder.

Generates single-page, statically-laid-out Mach-O executables that satisfy
AMFI on Apple Silicon (LC_LOAD_DYLINKER + LC_LOAD_DYLIB present) while
executing raw `svc #0x80` syscalls and exiting before returning to the
libSystem runtime.

The emitted binary embeds a placeholder ad-hoc code signature with the
correct on-disk layout; the CLI replaces it with a valid `codesign`-produced
signature before execution.
"""

import hashlib
import struct

from binary_gen.core.platform import DecodedInstruction, InstructionDecoder, Platform

# ─────────────────────────────────────────────────────────
# Mach-O constants
# ─────────────────────────────────────────────────────────

MACOS_BASE = 0x100000000

_MH_MAGIC_64 = 0xFEEDFACF
# On-disk (little-endian) magic; also used by `analysis.detect_platform`.
MACHO_MAGIC_64 = _MH_MAGIC_64.to_bytes(4, "little")  # b"\xcf\xfa\xed\xfe"
_CPU_TYPE_ARM64 = 0x0100000C
_MH_EXECUTE = 0x2

# Mach-O header flags
_MH_NOUNDEFS = 0x1
_MH_DYLDLINK = 0x4
_MH_PIE = 0x200000

# VM protection bits (vm_prot_t)
_VM_PROT_READ = 0x1
_VM_PROT_WRITE = 0x2
_VM_PROT_EXECUTE = 0x4
_VM_PROT_RX = _VM_PROT_READ | _VM_PROT_EXECUTE  # 5
_VM_PROT_R = _VM_PROT_READ  # 1

# Load command IDs
_LC_SEGMENT_64 = 0x19
_LC_MAIN = 0x80000028
_LC_LOAD_DYLINKER = 0xE
_LC_LOAD_DYLIB = 0xC
_LC_CODE_SIGNATURE = 0x1D

# Load command sizes (padded to 8-byte alignment)
_LC_MAIN_SIZE = 24
_LC_SEG_SIZE = 72
_LC_CODESIG_SIZE = 16

_DYLINKER_STR = b"/usr/lib/dyld\x00"  # 14 bytes
_DYLIB_STR = b"/usr/lib/libSystem.B.dylib\x00"  # 27 bytes

_LC_DYLINKER_SIZE = (12 + len(_DYLINKER_STR) + 7) & ~7  # 32 bytes
_LC_DYLIB_SIZE = (24 + len(_DYLIB_STR) + 7) & ~7  # 56 bytes

# libSystem.B.dylib version fields packed into LC_LOAD_DYLIB.
# Format is M.m.p encoded as 0xMMMMmmpp.
_LIBSYSTEM_CURRENT_VERSION = 0x050C0B00  # 1292.11.0
_LIBSYSTEM_COMPAT_VERSION = 0x00010000  # 1.0.0

# Load command count: PAGEZERO, TEXT, LINKEDIT, MAIN, DYLINKER, DYLIB, CODESIG.
_NCMDS = 7

_SIZEOFCMDS = (
    _LC_SEG_SIZE * 3  # __PAGEZERO, __TEXT, __LINKEDIT
    + _LC_MAIN_SIZE  # LC_MAIN
    + _LC_DYLINKER_SIZE  # LC_LOAD_DYLINKER
    + _LC_DYLIB_SIZE  # LC_LOAD_DYLIB
    + _LC_CODESIG_SIZE  # LC_CODE_SIGNATURE
)  # 344 bytes

# ─────────────────────────────────────────────────────────
# Code signature constants
# ─────────────────────────────────────────────────────────

_CS_MAGIC_EMBEDDED_SIGNATURE = 0xFADE0CC0
_CS_MAGIC_CODEDIRECTORY = 0xFADE0C02
_CSSLOT_CODEDIRECTORY = 0
_CS_ADHOC = 0x2
_CS_HASH_SHA256 = 2
_CS_SHA256_DIGEST_SIZE = 32

# CodeDirectory layout: 44-byte fixed header, 4-byte null identity string,
# then one 32-byte SHA-256 page hash → 80 bytes total.
_CD_HEADER_SIZE = 44
_CD_IDENT_SIZE = 4  # single null terminator (empty identity string)
_CD_TOTAL_SIZE = _CD_HEADER_SIZE + _CD_IDENT_SIZE + _CS_SHA256_DIGEST_SIZE  # 80

# SuperBlob layout: 12-byte header, one 8-byte index entry, then the CD.
_SB_HEADER_SIZE = 12
_SB_INDEX_SIZE = 8
_CD_OFFSET_IN_SUPERBLOB = _SB_HEADER_SIZE + _SB_INDEX_SIZE  # 20

# ─────────────────────────────────────────────────────────
# Layout constants
# ─────────────────────────────────────────────────────────
#
# LC_MAIN rather than LC_UNIXTHREAD: 24 bytes instead of 288, and fewer edge
# cases with modern dyld. dyld runs the libSystem initializers, then jumps to
# entryoff; the code exits by raw syscall, so the result is the same either way.
#
# File layout (all offsets fixed):
#   [0x0000, 0x0020)  Mach-O header          32 bytes
#   [0x0020, 0x0178)  Load commands         344 bytes
#                       __PAGEZERO seg        72 bytes
#                       __TEXT     seg        72 bytes
#                       __LINKEDIT seg        72 bytes
#                       LC_MAIN               24 bytes
#                       LC_LOAD_DYLINKER      32 bytes
#                       LC_LOAD_DYLIB         56 bytes
#                       LC_CODE_SIGNATURE     16 bytes
#   [0x0178, 0x4000)  <code> + <data> + zero padding
#   [0x4000, 0x4064)  __LINKEDIT: 100-byte ad-hoc code signature

# Apple Silicon uses 16KB pages (2^14). Must match the CodeDirectory pageSize
# field (log2 = 14) and all segment alignment.
_PAGE_SIZE = 16384
_PAGE_MASK = _PAGE_SIZE - 1
_PAGE_SHIFT = 14  # log2(_PAGE_SIZE)

_SIG_BLOB_SIZE = 100  # fits one-page __TEXT (header + index + CD = 12 + 8 + 80)
assert _SIG_BLOB_SIZE == _SB_HEADER_SIZE + _SB_INDEX_SIZE + _CD_TOTAL_SIZE

MACOS_CODE_OFFSET = 32 + _SIZEOFCMDS  # 376 = 0x178


# ─────────────────────────────────────────────────────────
# ARM64 instruction encoding / decoding
# ─────────────────────────────────────────────────────────

# Bit fields shared by the encoders and decoders.
_MOVZ_MASK = 0xFF800000
_MOVZ_BASE = 0xD2800000
_ADR_MASK = 0x9F000000
_ADR_BASE = 0x10000000
_SVC_MACOS_WORD = 0xD4001001
_INSN_SIZE = 4  # all ARM64 instructions are 4 bytes


# ── Encoders ──────────────────────────────────────────────


def arm64_movz(reg: int, imm: int) -> bytes:
    """
    Encode `MOVZ Xn, #imm` (zero-extended, no shift).

    Args:
        reg: Destination register number (0–31).
        imm: 16-bit unsigned immediate (0–0xFFFF).

    Raises:
        ValueError: If `imm` does not fit in 16 bits.
    """
    if not (0 <= imm <= 0xFFFF):
        raise ValueError(f"Immediate {imm} out of range for MOVZ (0..0xFFFF)")

    return struct.pack("<I", _MOVZ_BASE | (imm << 5) | reg)


def arm64_adr(reg: int, offset: int) -> bytes:
    """
    Encode `ADR Xn, #offset` (PC-relative label, ±1MB range).

    Args:
        reg: Destination register number (0–31).
        offset: Signed PC-relative byte offset in the range [-2^20, 2^20 - 1].

    Raises:
        ValueError: If `offset` is outside the ±1MB ADR range.
    """
    if not (-(1 << 20) <= offset < (1 << 20)):
        raise ValueError(f"ADR offset {offset} out of ±1MB range")

    immlo = offset & 0x3
    immhi = (offset >> 2) & 0x7FFFF

    return struct.pack("<I", (immlo << 29) | _ADR_BASE | (immhi << 5) | reg)


SVC_MACOS = struct.pack("<I", _SVC_MACOS_WORD)  # svc #0x80


# ── Decoders ──────────────────────────────────────────────


def _decode_movz(data: bytes, file_offset: int) -> DecodedInstruction | None:
    """Decode `MOVZ Xn, #imm16`."""
    if len(data) < _INSN_SIZE:
        return None

    word = struct.unpack("<I", data[:4])[0]

    if (word & _MOVZ_MASK) != _MOVZ_BASE:
        return None

    reg = word & 0x1F
    imm = (word >> 5) & 0xFFFF

    return DecodedInstruction(
        offset=file_offset,
        size=_INSN_SIZE,
        mnemonic="movz",
        text=f"movz x{reg}, #{imm} (0x{imm:x})",
        register=f"x{reg}",
        immediate=imm,
    )


def _decode_adr(data: bytes, file_offset: int) -> DecodedInstruction | None:
    """Decode `ADR Xn, #offset`."""
    if len(data) < _INSN_SIZE:
        return None

    word = struct.unpack("<I", data[:4])[0]

    if (word & _ADR_MASK) != _ADR_BASE:
        return None

    reg = word & 0x1F
    immlo = (word >> 29) & 0x3
    immhi = (word >> 5) & 0x7FFFF
    offset = (immhi << 2) | immlo

    if offset & (1 << 20):
        offset -= 1 << 21

    target = file_offset + offset

    return DecodedInstruction(
        offset=file_offset,
        size=_INSN_SIZE,
        mnemonic="adr",
        text=f"adr x{reg}, #{offset} (target: file offset 0x{target:x})",
        register=f"x{reg}",
        immediate=offset,
    )


def _decode_svc(data: bytes, file_offset: int) -> DecodedInstruction | None:
    """Decode `svc #0x80` (macOS syscall)."""
    if len(data) < _INSN_SIZE:
        return None

    word = struct.unpack("<I", data[:4])[0]

    if word != _SVC_MACOS_WORD:
        return None

    return DecodedInstruction(
        offset=file_offset,
        size=_INSN_SIZE,
        mnemonic="svc",
        text="svc #0x80",
    )


#: Ordered list of ARM64 instruction decoders for the analysis pipeline.
ARM64_DECODERS: list[InstructionDecoder] = [_decode_movz, _decode_adr, _decode_svc]


# ─────────────────────────────────────────────────────────
# Mach-O binary builder
# ─────────────────────────────────────────────────────────

# macos_print uses a fixed 8-instruction sequence (32 bytes).
# The adr is instruction 1 (byte offset 4 from code start).
# The string data follows immediately after all 8 instructions (byte offset 32).
# _PRINT_ADR_TO_STRING = 32 - 4 = 28.
# This value is load-bearing: it must stay in sync with the instruction layout below.
_PRINT_ADR_TO_STRING = (8 * 4) - (1 * 4)  # 28
assert _PRINT_ADR_TO_STRING == 28, "adr offset derivation changed - update arm64_adr call"


def _make_code_signature(text_page: bytes) -> bytes:
    """
    Build a minimal ad-hoc embedded-signature SuperBlob for one PAGE_SIZE page.

    Establishes the correct file layout so the CLI's `codesign` call can
    replace the content with a valid signature without restructuring the file.

    Args:
        text_page: Exactly one page (_PAGE_SIZE bytes) of __TEXT contents.

    Raises:
        ValueError: If `text_page` is not exactly _PAGE_SIZE bytes.
    """
    if len(text_page) != _PAGE_SIZE:
        raise ValueError(f"Text page must be exactly {_PAGE_SIZE} bytes.")

    page_hash = hashlib.sha256(text_page).digest()

    # CodeDirectory (80 bytes):
    #   44-byte header, 4-byte null identity string, 32-byte SHA-256 page hash.
    cd_header = struct.pack(
        ">IIIIIIIIIBBBBI",
        _CS_MAGIC_CODEDIRECTORY,
        _CD_TOTAL_SIZE,  # length
        0x20400,  # version 2.4.0
        _CS_ADHOC,
        _CD_HEADER_SIZE + _CD_IDENT_SIZE,  # hashOffset (48)
        _CD_HEADER_SIZE,  # identOffset (44)
        0,  # nSpecialSlots
        1,  # nCodeSlots (one page)
        _PAGE_SIZE,  # codeLimit
        _CS_SHA256_DIGEST_SIZE,  # hashSize
        _CS_HASH_SHA256,  # hashType
        0,  # platform
        _PAGE_SHIFT,  # pageSize: log2(16384) = 14 on Apple Silicon
        0,  # spare2
    )

    code_dir = cd_header + b"\x00" * _CD_IDENT_SIZE + page_hash

    # SuperBlob (100 bytes total):
    #   header (12) + one index entry (8) + CodeDirectory (80)
    blob = struct.pack(">III", _CS_MAGIC_EMBEDDED_SIGNATURE, _SIG_BLOB_SIZE, 1)
    blob += struct.pack(">II", _CSSLOT_CODEDIRECTORY, _CD_OFFSET_IN_SUPERBLOB)
    blob += code_dir

    return blob


def _pad_segname(name: bytes) -> bytes:
    """Pad a Mach-O segment name to the fixed 16-byte field."""
    if len(name) > 16:
        raise ValueError(f"Segment name {name!r} exceeds 16 bytes")

    return name.ljust(16, b"\x00")


def build_macos_binary(code: bytes, data: bytes = b"") -> bytes:
    """
    Build a runnable macOS arm64 Mach-O binary.

    Uses LC_MAIN as the entry point: dyld loads libSystem and runs its
    initializers, then jumps to entryoff (MACOS_CODE_OFFSET). The provided
    code is expected to exit via raw `svc #0x80` syscall without returning.

    Embeds a placeholder ad-hoc code signature. The CLI replaces this with
    a valid signature via `codesign` before the binary can be executed.

    Args:
        code: ARM64 machine code starting at MACOS_CODE_OFFSET.
        data: Optional read-only data placed immediately after `code`.

    Raises:
        ValueError: If header + code + data does not fit in one page.
    """
    payload = code + data

    if MACOS_CODE_OFFSET + len(payload) > _PAGE_SIZE:
        raise ValueError(
            f"Payload too large: header ({MACOS_CODE_OFFSET} B) + payload "
            f"({len(payload)} B) exceeds one page ({_PAGE_SIZE} B)."
        )

    sig_file_offset = _PAGE_SIZE
    linkedit_vmaddr = MACOS_BASE + _PAGE_SIZE
    linkedit_vmsize = (_SIG_BLOB_SIZE + _PAGE_MASK) & ~_PAGE_MASK

    mh = struct.pack(
        "<IIIIIIII",
        _MH_MAGIC_64,
        _CPU_TYPE_ARM64,
        0,  # cpusubtype
        _MH_EXECUTE,
        _NCMDS,
        _SIZEOFCMDS,
        _MH_NOUNDEFS | _MH_DYLDLINK | _MH_PIE,
        0,  # reserved
    )

    pagezero_seg = struct.pack(
        "<II16sQQQQIIII",
        _LC_SEGMENT_64,
        _LC_SEG_SIZE,
        _pad_segname(b"__PAGEZERO"),
        0,  # vmaddr
        MACOS_BASE,  # vmsize
        0,  # fileoff
        0,  # filesize
        0,  # maxprot
        0,  # initprot
        0,  # nsects
        0,  # flags
    )

    text_seg = struct.pack(
        "<II16sQQQQIIII",
        _LC_SEGMENT_64,
        _LC_SEG_SIZE,
        _pad_segname(b"__TEXT"),
        MACOS_BASE,  # vmaddr
        _PAGE_SIZE,  # vmsize
        0,  # fileoff
        _PAGE_SIZE,  # filesize
        _VM_PROT_RX,  # maxprot
        _VM_PROT_RX,  # initprot
        0,  # nsects
        0,  # flags
    )

    linkedit_seg = struct.pack(
        "<II16sQQQQIIII",
        _LC_SEGMENT_64,
        _LC_SEG_SIZE,
        _pad_segname(b"__LINKEDIT"),
        linkedit_vmaddr,  # vmaddr
        linkedit_vmsize,  # vmsize
        sig_file_offset,  # fileoff
        _SIG_BLOB_SIZE,  # filesize
        _VM_PROT_R,  # maxprot
        _VM_PROT_R,  # initprot
        0,  # nsects
        0,  # flags
    )

    main_cmd = struct.pack("<IIQQ", _LC_MAIN, _LC_MAIN_SIZE, MACOS_CODE_OFFSET, 0)

    dylinker = (
        struct.pack("<III", _LC_LOAD_DYLINKER, _LC_DYLINKER_SIZE, 12)
        + _DYLINKER_STR
        + b"\x00" * (_LC_DYLINKER_SIZE - 12 - len(_DYLINKER_STR))
    )

    dylib = (
        struct.pack(
            "<IIIIII",
            _LC_LOAD_DYLIB,
            _LC_DYLIB_SIZE,
            24,  # name offset (start of string within this LC)
            0,  # timestamp
            _LIBSYSTEM_CURRENT_VERSION,
            _LIBSYSTEM_COMPAT_VERSION,
        )
        + _DYLIB_STR
        + b"\x00" * (_LC_DYLIB_SIZE - 24 - len(_DYLIB_STR))
    )

    codesig_lc = struct.pack(
        "<IIII", _LC_CODE_SIGNATURE, _LC_CODESIG_SIZE, sig_file_offset, _SIG_BLOB_SIZE
    )

    header = mh + pagezero_seg + text_seg + linkedit_seg + main_cmd + dylinker + dylib + codesig_lc
    text_page = (header + payload).ljust(_PAGE_SIZE, b"\x00")

    return text_page + _make_code_signature(text_page)


# ─────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────


def macos_print(s: str) -> bytes:
    """
    Build a macOS arm64 binary that writes `s` (plus a newline) to stdout
    and exits cleanly with status 0.

    Instruction layout (8 instructions = 32 bytes, string follows immediately):
      offset  0: mov x0, #1          stdout fd
      offset  4: adr x1, #28         PC-relative pointer to string data (32 - 4)
      offset  8: mov x2, #len        byte length of string + newline
      offset 12: mov x16, #4         write syscall
      offset 16: svc #0x80
      offset 20: mov x0, #0          exit code
      offset 24: mov x16, #1         exit syscall
      offset 28: svc #0x80
      offset 32: <string bytes>
    """
    data = s.encode("ascii") + b"\n"

    code = (
        arm64_movz(0, 1)  # mov x0, #1
        + arm64_adr(1, _PRINT_ADR_TO_STRING)  # adr x1, string_label
        + arm64_movz(2, len(data))  # mov x2, #len
        + arm64_movz(16, 4)  # mov x16, #4 (write)
        + SVC_MACOS  # svc #0x80
        + arm64_movz(0, 0)  # mov x0, #0
        + arm64_movz(16, 1)  # mov x16, #1 (exit)
        + SVC_MACOS  # svc #0x80
    )

    return build_macos_binary(code, data)


def macos_print_exit(s: str, n: int) -> bytes:
    """
    Like `macos_print`, but exits with code `n` instead of 0.

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
        arm64_movz(0, 1)  # mov x0, #1  (stdout fd)
        + arm64_adr(1, _PRINT_ADR_TO_STRING)  # adr x1, string_label
        + arm64_movz(2, len(data))  # mov x2, #len
        + arm64_movz(16, 4)  # mov x16, #4 (write)
        + SVC_MACOS  # svc #0x80
        + arm64_movz(0, n)  # mov x0, #n  (exit code)
        + arm64_movz(16, 1)  # mov x16, #1 (exit)
        + SVC_MACOS  # svc #0x80
    )

    return build_macos_binary(code, data)


def macos_exit(n: int) -> bytes:
    """
    Build a minimal macOS arm64 binary that exits with status code `n`.

    Args:
        n: Exit status, 0-255.

    Raises:
        ValueError: If `n` is outside [0, 255].
    """
    if not (0 <= n <= 255):
        raise ValueError("Exit code must be between 0 and 255.")

    code = arm64_movz(0, n) + arm64_movz(16, 1) + SVC_MACOS

    return build_macos_binary(code)


# ─────────────────────────────────────────────────────────
# Builder
# ─────────────────────────────────────────────────────────


class MacArmBuilder:
    """macOS arm64 implementation of the PlatformBuilder protocol."""

    platform = Platform.MAC_ARM

    def build_print(self, s: str) -> bytes:
        return macos_print(s)

    def build_exit(self, n: int) -> bytes:
        return macos_exit(n)

    def build_print_exit(self, s: str, n: int) -> bytes:
        return macos_print_exit(s, n)


builder = MacArmBuilder()
