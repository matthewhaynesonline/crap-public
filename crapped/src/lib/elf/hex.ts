/**
 * Where untrusted model text becomes bytes. Parsing happens once, here;
 * everything downstream takes a `Uint8Array`. Must agree with
 * `binary_gen.core.parse_hex`, the Python reference.
 */

import { err, ok, type Result } from "../result";

/** Bytes per row in a {@link hexDump}, matching the conventional `xxd` width. */
const DUMP_WIDTH = 16;

/** One rendered row of a hex dump: address, byte columns, ASCII gutter. */
interface DumpRow {
  /** File offset of the first byte in this row. */
  readonly offset: number;
  /** Two-digit lowercase hex for each byte present, up to {@link DUMP_WIDTH}. */
  readonly bytes: readonly string[];
  /** Printable ASCII per byte, with `.` standing in for anything unprintable. */
  readonly ascii: string;
}

/**
 * Strips a leading `0x` and all whitespace, since models often wrap or space
 * their output. Even length and hex-only digits are checked first, so
 * `parseInt` can't quietly yield `NaN`. The error is a human-readable reason.
 */
function parseHex(text: string): Result<Uint8Array, string> {
  const clean = text.trim().replace(/^0x/i, "").replace(/\s+/g, "");

  if (clean.length === 0) {
    return err("empty hex string");
  }

  if (clean.length % 2 !== 0) {
    return err(`odd length (${clean.length} chars): hex must come in byte pairs`);
  }

  const bad = clean.match(/[^0-9a-fA-F]/);

  if (bad !== null) {
    return err(`non-hex character ${JSON.stringify(bad[0])} at index ${bad.index}`);
  }

  const bytes = new Uint8Array(clean.length / 2);

  for (let i = 0; i < bytes.length; i += 1) {
    bytes[i] = Number.parseInt(clean.substring(i * 2, i * 2 + 2), 16);
  }

  return ok(bytes);
}

/** Continuous lowercase hex; the inverse of {@link parseHex}. */
function toHex(bytes: Uint8Array): string {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/**
 * `xxd`-style rows rather than one string, so the view can mark single byte
 * cells: the interesting failures are single wrong bytes. The last row may be
 * short.
 */
function hexDump(bytes: Uint8Array, width: number = DUMP_WIDTH): readonly DumpRow[] {
  const rows: DumpRow[] = [];

  for (let offset = 0; offset < bytes.length; offset += width) {
    const chunk = bytes.subarray(offset, offset + width);

    rows.push({
      offset,
      bytes: Array.from(chunk, (byte) => byte.toString(16).padStart(2, "0")),
      ascii: Array.from(chunk, (byte) =>
        byte >= 0x20 && byte < 0x7f ? String.fromCharCode(byte) : ".",
      ).join(""),
    });
  }

  return rows;
}

export { parseHex, toHex, hexDump, DUMP_WIDTH, type DumpRow };
