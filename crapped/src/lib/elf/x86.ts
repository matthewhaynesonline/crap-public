/**
 * Decodes only the four instruction forms `binary-gen` emits, which is all the
 * model was trained on. Not a general disassembler.
 *
 * Port of the decoders in `binary_gen.core.linux_x86`; keep the encodings in
 * step with it, since it defines what the model was trained to emit.
 */

/** `REX.W`, the 64-bit operand-size prefix on every emitted `mov`. */
const REX_W = 0x48;

/** Opcode byte → destination register for `REX.W mov r64, imm64`. */
const MOV_REGISTERS: Readonly<Record<number, Register>> = {
  0xb8: "rax",
  0xbf: "rdi",
  0xba: "rdx",
};

/** `REX.W(1) + opcode(1) + imm64(8)`. */
const MOV_SIZE = 10;

/** Opcode bytes for `lea rsi, [rip + disp32]`. */
const LEA_RSI_RIP = [0x48, 0x8d, 0x35] as const;

/** `prefix(3) + disp32(4)`. */
const LEA_SIZE = 7;

/** The two-byte `syscall` opcode. */
const SYSCALL = [0x0f, 0x05] as const;

const SYSCALL_SIZE = 2;

/**
 * Caps the list a garbage byte stream can produce. Matches `max_instructions`
 * in `analysis.py`.
 */
const MAX_INSTRUCTIONS = 20;

/** The three registers `binary-gen` loads immediates into. */
type Register = "rax" | "rdi" | "rdx";

/**
 * Structured fields sit beside the display `text` so checks never re-parse
 * prose, as in `DecodedInstruction` in `binary_gen.core.platform`.
 */
type Instruction =
  | {
      readonly mnemonic: "mov";
      readonly offset: number;
      readonly size: number;
      readonly text: string;
      readonly register: Register;
      readonly immediate: number;
    }
  | {
      readonly mnemonic: "lea";
      readonly offset: number;
      readonly size: number;
      readonly text: string;
      /** Signed displacement from the address of the *next* instruction. */
      readonly displacement: number;
      /** File offset the displacement resolves to. */
      readonly target: number;
    }
  | {
      readonly mnemonic: "syscall";
      readonly offset: number;
      readonly size: number;
      readonly text: string;
    };

/** Where the instruction stream ended and the string payload begins. */
interface Decoding {
  readonly instructions: readonly Instruction[];
  /** Bytes consumed by the instructions, relative to the start of `code`. */
  readonly consumed: number;
}

/**
 * Decode until an instruction isn't recognised. `binary-gen` puts the string
 * straight after the code with no marker, so the first byte that doesn't
 * decode is where the payload starts.
 *
 * @param baseOffset - File offset of `code[0]`, so reported offsets are absolute.
 */
function decode(code: Uint8Array, baseOffset: number): Decoding {
  const instructions: Instruction[] = [];
  let position = 0;

  while (position < code.length && instructions.length < MAX_INSTRUCTIONS) {
    const instruction = decodeOne(code.subarray(position), baseOffset + position);

    if (instruction === null) {
      break;
    }

    instructions.push(instruction);
    position += instruction.size;
  }

  return { instructions, consumed: position };
}

function decodeOne(data: Uint8Array, offset: number): Instruction | null {
  return decodeMov(data, offset) ?? decodeLea(data, offset) ?? decodeSyscall(data, offset);
}

/**
 * `REX.W mov r64, imm64`. The immediate narrows from `BigInt` to `number`,
 * lossless for what `binary-gen` emits (syscall numbers, descriptors, lengths,
 * exit codes) and comparable with plain lengths.
 */
function decodeMov(data: Uint8Array, offset: number): Instruction | null {
  if (data.length < MOV_SIZE || data[0] !== REX_W) {
    return null;
  }

  const register = MOV_REGISTERS[data[1]!];

  if (register === undefined) {
    return null;
  }

  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const immediate = Number(view.getBigUint64(2, true));

  return {
    mnemonic: "mov",
    offset,
    size: MOV_SIZE,
    text: `mov ${register}, ${immediate} (0x${immediate.toString(16)})`,
    register,
    immediate,
  };
}

/** `lea rsi, [rip + disp32]`; RIP is the address after this instruction. */
function decodeLea(data: Uint8Array, offset: number): Instruction | null {
  if (data.length < LEA_SIZE || !startsWith(data, LEA_RSI_RIP)) {
    return null;
  }

  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const displacement = view.getInt32(3, true);

  return {
    mnemonic: "lea",
    offset,
    size: LEA_SIZE,
    text: `lea rsi, [rip + ${displacement}]`,
    displacement,
    target: offset + LEA_SIZE + displacement,
  };
}

function decodeSyscall(data: Uint8Array, offset: number): Instruction | null {
  if (data.length < SYSCALL_SIZE || !startsWith(data, SYSCALL)) {
    return null;
  }

  return { mnemonic: "syscall", offset, size: SYSCALL_SIZE, text: "syscall" };
}

function startsWith(data: Uint8Array, prefix: readonly number[]): boolean {
  return prefix.every((byte, index) => data[index] === byte);
}

export { decode, MAX_INSTRUCTIONS, type Instruction, type Decoding, type Register };
