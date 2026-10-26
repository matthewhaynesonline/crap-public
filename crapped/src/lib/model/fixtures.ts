/**
 * Builds the inspector fixtures. **Not part of the demo's claim:** the model
 * emits its bytes with no builder in the loop. Used only by the stub backend.
 *
 * Port of `binary_gen.core.linux_x86`, pinned by `npm run check:elf`. It also
 * builds deliberately wrong binaries ({@link Flaw}), the near misses the
 * finetune actually makes.
 */

import type { Flaw } from "./types";

const ELF_HEADER_SIZE = 64;
const PROGRAM_HEADER_SIZE = 56;

/** Virtual address the single PT_LOAD segment is mapped at. */
const LOAD_BASE = 0x400000;

/** Code begins immediately after the ELF header and the one program header. */
const CODE_OFFSET = ELF_HEADER_SIZE + PROGRAM_HEADER_SIZE;

/** `p_align`: 2 MiB, the x86_64 large-page alignment. */
const PAGE_ALIGN = 0x200000;

const SYS_WRITE = 1;
const SYS_EXIT = 60;
const STDOUT = 1;

/**
 * From RIP after the `lea` to the string: code size 61 minus RIP offset 27.
 * Changes whenever the {@link buildPrint} instruction sequence does.
 */
const LEA_TO_STRING = 34;

/**
 * The fixed layout that makes {@link LEA_TO_STRING} a constant:
 *
 *     0   mov rax, SYS_WRITE     10 bytes
 *     10  mov rdi, STDOUT        10
 *     20  lea rsi, [rip + 34]     7
 *     27  mov rdx, len(data)     10
 *     37  syscall                 2
 *     39  mov rax, SYS_EXIT      10
 *     49  mov rdi, exitCode      10
 *     59  syscall                 2
 *     61  <data>
 *
 * @param message - ASCII; a newline is appended, as `binary-gen` does.
 * @param exitCode - 0 to 255.
 */
function buildPrint(message: string, exitCode: number = 0, flaw: Flaw = "none"): Uint8Array {
  const data = new TextEncoder().encode(`${message}\n`);

  // Overstate rdx by one: the finetune's classic off-by-one.
  const declaredLength = flaw === "write-length" ? data.length + 1 : data.length;

  const code = concat(
    movImm("rax", SYS_WRITE),
    movImm("rdi", STDOUT),
    leaRsiRip(LEA_TO_STRING),
    movImm("rdx", declaredLength),
    syscall(),
    movImm("rax", SYS_EXIT),
    movImm("rdi", exitCode),
    syscall(),
  );

  return damage(assemble(code, data), flaw);
}

/** @param exitCode - 0 to 255. */
function buildExit(exitCode: number, flaw: Flaw = "none"): Uint8Array {
  const code = concat(movImm("rax", SYS_EXIT), movImm("rdi", exitCode), syscall());

  return damage(assemble(code, new Uint8Array(0)), flaw);
}

/**
 * One PT_LOAD segment, no section headers, symbols or dynamic linking: the
 * smallest thing the kernel will run. The entry point is the first code byte.
 */
function assemble(code: Uint8Array, data: Uint8Array): Uint8Array {
  const payload = concat(code, data);
  const totalSize = CODE_OFFSET + payload.length;
  const image = new Uint8Array(totalSize);
  const view = new DataView(image.buffer);

  // e_ident: magic(4) + class + data + version + osabi + abiversion + 7 pad
  image.set([0x7f, 0x45, 0x4c, 0x46, 2, 1, 1, 0, 0], 0);

  view.setUint16(16, 2, true); // e_type = ET_EXEC
  view.setUint16(18, 0x3e, true); // e_machine = EM_X86_64
  view.setUint32(20, 1, true); // e_version = EV_CURRENT
  view.setBigUint64(24, BigInt(LOAD_BASE + CODE_OFFSET), true); // e_entry
  view.setBigUint64(32, BigInt(ELF_HEADER_SIZE), true); // e_phoff
  view.setBigUint64(40, 0n, true); // e_shoff: no section headers
  view.setUint32(48, 0, true); // e_flags
  view.setUint16(52, ELF_HEADER_SIZE, true); // e_ehsize
  view.setUint16(54, PROGRAM_HEADER_SIZE, true); // e_phentsize
  view.setUint16(56, 1, true); // e_phnum
  view.setUint16(58, 64, true); // e_shentsize: unused, conventionally set
  view.setUint16(60, 0, true); // e_shnum
  view.setUint16(62, 0, true); // e_shstrndx

  const phdr = ELF_HEADER_SIZE;
  view.setUint32(phdr, 1, true); // p_type = PT_LOAD
  view.setUint32(phdr + 4, 5, true); // p_flags = R|X
  view.setBigUint64(phdr + 8, 0n, true); // p_offset: segment starts at byte 0
  view.setBigUint64(phdr + 16, BigInt(LOAD_BASE), true); // p_vaddr
  view.setBigUint64(phdr + 24, BigInt(LOAD_BASE), true); // p_paddr
  view.setBigUint64(phdr + 32, BigInt(totalSize), true); // p_filesz
  view.setBigUint64(phdr + 40, BigInt(totalSize), true); // p_memsz
  view.setBigUint64(phdr + 48, BigInt(PAGE_ALIGN), true); // p_align

  image.set(payload, CODE_OFFSET);

  return image;
}

/** `write-length` changes an operand, so {@link buildPrint} handles it instead. */
function damage(image: Uint8Array, flaw: Flaw): Uint8Array {
  switch (flaw) {
    case "bad-magic":
      // Flip 'E' (0x45) to 'F' (0x46), the error in the write-up's thumbnail.
      return concat(new Uint8Array([image[0]!, 0x46]), image.subarray(2));

    case "truncated":
      return image.subarray(0, Math.floor(image.length * 0.8));

    case "none":
    case "write-length":
      return image;

    default: {
      const unhandled: never = flaw;
      throw new Error(`unhandled flaw: ${String(unhandled)}`);
    }
  }
}

/** Encode `REX.W mov r64, imm64`. */
function movImm(register: "rax" | "rdi" | "rdx", immediate: number): Uint8Array {
  const opcode = { rax: 0xb8, rdi: 0xbf, rdx: 0xba }[register];
  const bytes = new Uint8Array(10);

  bytes[0] = 0x48;
  bytes[1] = opcode;
  new DataView(bytes.buffer).setBigUint64(2, BigInt(immediate), true);

  return bytes;
}

/** Encode `lea rsi, [rip + disp32]`. */
function leaRsiRip(displacement: number): Uint8Array {
  const bytes = new Uint8Array(7);

  bytes.set([0x48, 0x8d, 0x35], 0);
  new DataView(bytes.buffer).setInt32(3, displacement, true);

  return bytes;
}

function syscall(): Uint8Array {
  return new Uint8Array([0x0f, 0x05]);
}

function concat(...parts: readonly Uint8Array[]): Uint8Array {
  const total = parts.reduce((sum, part) => sum + part.length, 0);
  const joined = new Uint8Array(total);
  let at = 0;

  for (const part of parts) {
    joined.set(part, at);
    at += part.length;
  }

  return joined;
}

export { buildPrint, buildExit };
