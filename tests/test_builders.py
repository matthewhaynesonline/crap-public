import struct

import pytest
from binary_gen.core import get_builder, parse_hex
from binary_gen.core.platform import Platform


@pytest.mark.parametrize("message", ["", "hello", "%s%n", "123"])
def test_elf_layout(message: str) -> None:
    binary = get_builder(Platform.LINUX_X86).build_print(message)
    assert binary[:7] == b"\x7fELF\x02\x01\x01"
    entry, program_offset, section_offset = struct.unpack_from("<QQQ", binary, 24)
    assert entry == 0x400000 + 120
    assert program_offset == 64
    assert section_offset == 0
    kind, flags, offset, address, _, file_size, memory_size, _ = struct.unpack_from(
        "<IIQQQQQQ", binary, 64
    )
    assert (kind, flags, offset, address) == (1, 5, 0, 0x400000)
    assert file_size == memory_size == len(binary)
    displacement = struct.unpack_from("<i", binary, 120 + 23)[0]
    payload_offset = 120 + 27 + displacement
    assert binary[payload_offset:] == message.encode("ascii") + b"\n"
    assert struct.unpack_from("<Q", binary, 120 + 29)[0] == len(message) + 1


def test_macho_load_commands_and_signature() -> None:
    binary = get_builder(Platform.MAC_ARM).build_print("%s%n")
    magic, cpu, _, file_type, count, commands_size, _, _ = struct.unpack_from("<8I", binary)
    assert (magic, cpu, file_type) == (0xFEEDFACF, 0x100000C, 2)
    offset = 32
    commands: dict[int, tuple[int, int]] = {}
    for _ in range(count):
        command, size = struct.unpack_from("<II", binary, offset)
        assert size >= 8
        assert size % 8 == 0
        commands[command] = (offset, size)
        offset += size
    assert offset == 32 + commands_size
    assert 0x80000028 in commands  # LC_MAIN
    entry = struct.unpack_from("<Q", binary, commands[0x80000028][0] + 8)[0]
    assert offset <= entry < len(binary)
    signature_offset, signature_size = struct.unpack_from("<II", binary, commands[0x1D][0] + 8)
    assert signature_offset + signature_size == len(binary)
    assert struct.unpack_from(">I", binary, signature_offset)[0] == 0xFADE0CC0
    assert b"%s%n\n" in binary


@pytest.mark.parametrize("platform", list(Platform))
def test_builder_input_boundaries(platform: Platform) -> None:
    builder = get_builder(platform)
    with pytest.raises(UnicodeEncodeError):
        builder.build_print("é")
    for code in [-1, 256]:
        with pytest.raises(ValueError, match="Exit code"):
            builder.build_exit(code)
    for code in [0, 255]:
        assert builder.build_exit(code)


@pytest.mark.parametrize("hex_text", ["0", "zz", "0x00", "00-ff"])
def test_invalid_hex(hex_text: str) -> None:
    with pytest.raises(ValueError, match="Invalid hex"):
        parse_hex(hex_text)


def test_hex_whitespace() -> None:
    assert parse_hex(" 7f 45\n4c\t46 ") == b"\x7fELF"
    assert parse_hex("") == b""
