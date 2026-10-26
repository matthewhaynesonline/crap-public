/**
 * Structural inspection of a generated Linux x86_64 ELF, in the browser.
 *
 * The private `binary-gen` eval runs hex, structure and behavior stages; the
 * last one executes the binary, which a browser can't. So a binary can pass
 * everything here and still print the wrong string. The consistency notes catch
 * the behavioral bugs that are visible statically, like a `write` length that
 * disagrees with its payload.
 *
 * The layout is the fixed one `binary_gen.core.linux_x86` emits:
 *
 *     0x00  ELF header    (64 bytes)
 *     0x40  PT_LOAD phdr  (56 bytes)
 *     0x78  code
 *           data
 */

import { parseHex } from "./hex";
import { decode, type Instruction } from "./x86";

/** `\x7fELF`, the four bytes every ELF file opens with. */
const ELF_MAGIC = [0x7f, 0x45, 0x4c, 0x46] as const;

const ELF_HEADER_SIZE = 64;
const PROGRAM_HEADER_SIZE = 56;

/** Entry point offset: the code starts immediately after header + phdr. */
const CODE_OFFSET = ELF_HEADER_SIZE + PROGRAM_HEADER_SIZE;

/** `e_ident[EI_CLASS]` for a 64-bit object. */
const ELF_CLASS_64 = 2;

/** `e_ident[EI_DATA]` for little-endian. */
const ELF_DATA_LSB = 1;

/** `e_machine` for AMD x86-64. */
const MACHINE_X86_64 = 0x3e;

/** `p_type` for a loadable segment. */
const PT_LOAD = 1;

/** Linux syscall numbers we recognise in the consistency check. */
const SYS_WRITE = 1;

/** The parsed ELF64 header fields the report displays. */
interface ElfHeader {
  readonly class64: boolean;
  readonly littleEndian: boolean;
  readonly type: number;
  readonly machine: number;
  readonly entry: number;
  readonly programHeaderOffset: number;
  readonly programHeaderCount: number;
}

/** One program header, flags rendered in the conventional `RWX` form. */
interface Segment {
  readonly type: number;
  readonly typeName: string;
  readonly virtualAddress: number;
  readonly fileSize: number;
  readonly flags: string;
}

/** A statically checkable claim the binary makes about itself. */
type ConsistencyNote =
  | { readonly kind: "write-length-ok"; readonly declared: number }
  | { readonly kind: "write-length-mismatch"; readonly declared: number; readonly actual: number }
  | { readonly kind: "string-pointer-ok"; readonly target: number }
  | { readonly kind: "string-pointer-off"; readonly target: number; readonly dataOffset: number }
  | { readonly kind: "no-code" };

/** Everything successfully read out of a structurally sound binary. */
interface ElfImage {
  readonly header: ElfHeader;
  readonly segments: readonly Segment[];
  readonly instructions: readonly Instruction[];
  /** File offset where the string payload starts, or `null` if there is none. */
  readonly dataOffset: number | null;
  /** The payload decoded as ASCII, escaped for display; see {@link renderPayload}. */
  readonly dataText: string | null;
  readonly notes: readonly ConsistencyNote[];
}

/**
 * How far the output got. Stages match `binary_gen.core.eval.FailureStage`,
 * except `behavior` is unreachable here, so `sound` names it as unverified
 * rather than claiming a pass.
 */
type Inspection =
  | { readonly stage: "hex"; readonly error: string }
  | { readonly stage: "structure"; readonly bytes: Uint8Array; readonly error: string }
  | {
      readonly stage: "sound";
      readonly bytes: Uint8Array;
      readonly image: ElfImage;
      /** Always `"behavior"`: the browser cannot execute the binary to confirm it. */
      readonly unverified: "behavior";
    };

/**
 * Inspect raw model hex as a Linux x86_64 ELF. Stops at the first failing stage
 * and never throws; every problem comes back as an {@link Inspection}.
 */
function inspect(hex: string): Inspection {
  const parsed = parseHex(hex);

  if (!parsed.ok) {
    return { stage: "hex", error: parsed.error };
  }

  const bytes = parsed.value;
  const failure = checkStructure(bytes);

  if (failure !== null) {
    return { stage: "structure", bytes, error: failure };
  }

  return { stage: "sound", bytes, image: readImage(bytes), unverified: "behavior" };
}

/**
 * The first structural problem, or `null` if sound. Checks run in loader order,
 * so the message names the earliest real fault rather than a later symptom.
 */
function checkStructure(bytes: Uint8Array): string | null {
  if (bytes.length < ELF_HEADER_SIZE) {
    return `too short: ${bytes.length} bytes, need at least ${ELF_HEADER_SIZE} for an ELF header`;
  }

  if (!ELF_MAGIC.every((byte, index) => bytes[index] === byte)) {
    const found = Array.from(bytes.subarray(0, 4), (b) => b.toString(16).padStart(2, "0")).join("");

    return `bad ELF magic: expected 7f454c46, found ${found}`;
  }

  if (bytes[4] !== ELF_CLASS_64) {
    return `not a 64-bit object: EI_CLASS is ${bytes[4]}, expected ${ELF_CLASS_64}`;
  }

  if (bytes[5] !== ELF_DATA_LSB) {
    return `not little-endian: EI_DATA is ${bytes[5]}, expected ${ELF_DATA_LSB}`;
  }

  const header = readHeader(bytes);

  if (header.machine !== MACHINE_X86_64) {
    return `wrong architecture: e_machine is 0x${header.machine.toString(16)}, expected 0x3e (x86_64)`;
  }

  if (header.programHeaderCount === 0) {
    return "no program headers: nothing for the kernel to load";
  }

  const declaredEnd = header.programHeaderOffset + header.programHeaderCount * PROGRAM_HEADER_SIZE;

  if (declaredEnd > bytes.length) {
    return `program header table runs past end of file (needs ${declaredEnd} bytes, have ${bytes.length})`;
  }

  if (!readSegments(bytes, header).some((segment) => segment.type === PT_LOAD)) {
    return "no PT_LOAD segment found";
  }

  return null;
}

/**
 * Needs at least {@link ELF_HEADER_SIZE} bytes with magic and class checked. 64-bit
 * fields narrow from `BigInt` to `number`, which is lossless for the ~`0x400000`
 * addresses `binary-gen` emits.
 */
function readHeader(bytes: Uint8Array): ElfHeader {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);

  return {
    class64: bytes[4] === ELF_CLASS_64,
    littleEndian: bytes[5] === ELF_DATA_LSB,
    type: view.getUint16(16, true),
    machine: view.getUint16(18, true),
    entry: Number(view.getBigUint64(24, true)),
    programHeaderOffset: Number(view.getBigUint64(32, true)),
    programHeaderCount: view.getUint16(56, true),
  };
}

/** The table must already be known to fit in `bytes`. */
function readSegments(bytes: Uint8Array, header: ElfHeader): readonly Segment[] {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const segments: Segment[] = [];

  for (let index = 0; index < header.programHeaderCount; index += 1) {
    const at = header.programHeaderOffset + index * PROGRAM_HEADER_SIZE;
    const type = view.getUint32(at, true);
    const flags = view.getUint32(at + 4, true);

    segments.push({
      type,
      typeName: type === PT_LOAD ? "PT_LOAD" : `0x${type.toString(16)}`,
      virtualAddress: Number(view.getBigUint64(at + 16, true)),
      fileSize: Number(view.getBigUint64(at + 32, true)),
      // R=4, W=2, X=1, fixed width so columns line up.
      flags: `${flags & 4 ? "R" : "-"}${flags & 2 ? "W" : "-"}${flags & 1 ? "X" : "-"}`,
    });
  }

  return segments;
}

/** Only for bytes that passed {@link checkStructure}. */
function readImage(bytes: Uint8Array): ElfImage {
  const header = readHeader(bytes);
  const segments = readSegments(bytes, header);

  if (bytes.length <= CODE_OFFSET) {
    return {
      header,
      segments,
      instructions: [],
      dataOffset: null,
      dataText: null,
      notes: [{ kind: "no-code" }],
    };
  }

  const code = bytes.subarray(CODE_OFFSET);
  const { instructions, consumed } = decode(code, CODE_OFFSET);
  const hasData = consumed < code.length;
  const dataOffset = hasData ? CODE_OFFSET + consumed : null;
  const payload = hasData ? code.subarray(consumed) : null;

  return {
    header,
    segments,
    instructions,
    dataOffset,
    dataText: payload === null ? null : renderPayload(payload),
    notes: checkConsistency(instructions, dataOffset, payload?.length ?? 0),
  };
}

/**
 * Whitespace is escaped rather than shown as `.` because the trailing newline
 * matters: `binary-gen` appends one to every printed string.
 */
function renderPayload(payload: Uint8Array): string {
  const escapes: Readonly<Record<number, string>> = {
    0x0a: "\\n",
    0x0d: "\\r",
    0x09: "\\t",
    0x00: "\\0",
  };

  return Array.from(payload, (byte) => {
    if (byte in escapes) {
      return escapes[byte]!;
    }

    return byte >= 0x20 && byte < 0x7f
      ? String.fromCharCode(byte)
      : `\\x${byte.toString(16).padStart(2, "0")}`;
  }).join("");
}

/**
 * The closest a browser gets to running the binary: check the `write` length in
 * `rdx` and the address `lea rsi` resolves to against the payload. Those are
 * the finetune's usual near misses, a binary that runs but prints garbage or
 * the wrong length. An empty list means nothing checkable was found.
 */
function checkConsistency(
  instructions: readonly Instruction[],
  dataOffset: number | null,
  payloadLength: number,
): readonly ConsistencyNote[] {
  const notes: ConsistencyNote[] = [];

  if (instructions.length === 0) {
    return [{ kind: "no-code" }];
  }

  if (dataOffset === null) {
    return notes;
  }

  // `rdx` is only the write length after a `mov rax, SYS_WRITE`.
  let sawWrite = false;
  let declared: number | null = null;

  for (const instruction of instructions) {
    if (instruction.mnemonic !== "mov") {
      continue;
    }

    if (instruction.register === "rax" && instruction.immediate === SYS_WRITE) {
      sawWrite = true;
    }

    if (instruction.register === "rdx" && sawWrite) {
      declared = instruction.immediate;
    }
  }

  if (declared !== null) {
    notes.push(
      declared === payloadLength
        ? { kind: "write-length-ok", declared }
        : { kind: "write-length-mismatch", declared, actual: payloadLength },
    );
  }

  const lea = instructions.find((instruction) => instruction.mnemonic === "lea");

  if (lea !== undefined && lea.mnemonic === "lea") {
    notes.push(
      lea.target === dataOffset
        ? { kind: "string-pointer-ok", target: lea.target }
        : { kind: "string-pointer-off", target: lea.target, dataOffset },
    );
  }

  return notes;
}

export {
  inspect,
  CODE_OFFSET,
  type Inspection,
  type ElfImage,
  type ElfHeader,
  type Segment,
  type ConsistencyNote,
};
