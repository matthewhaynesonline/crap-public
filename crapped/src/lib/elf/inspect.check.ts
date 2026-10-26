/**
 * ELF inspector checks; run with `npm run check:elf`. The first case pins the
 * hand-ported fixtures in `model/fixtures.ts` to hex from the Python builder,
 * since drifted fixtures would be wrong in a way the inspector would approve.
 * The rest walk each report stage, failures included.
 *
 * Replace with `vitest` when the demo grows a real test setup.
 */

import { buildExit, buildPrint } from "../model/fixtures";
import { toHex } from "./hex";
import { inspect } from "./inspect";

/** Pasted verbatim from `binary_gen.core.linux_x86.linux_print("hello world")`. */
// One line each: splitting a hex constant invites a lost or doubled digit.
// prettier-ignore
const PYTHON_HELLO_WORLD = "7f454c4602010100000000000000000002003e0001000000780040000000000040000000000000000000000000000000000000004000380001004000000000000100000005000000000000000000000000004000000000000000400000000000c100000000000000c100000000000000000020000000000048b8010000000000000048bf0100000000000000488d352200000048ba0c000000000000000f0548b83c0000000000000048bf00000000000000000f0568656c6c6f20776f726c640a";

/** Pasted verbatim from `binary_gen.core.linux_x86.linux_exit(42)`. */
// prettier-ignore
const PYTHON_EXIT_42 = "7f454c4602010100000000000000000002003e00010000007800400000000000400000000000000000000000000000000000000040003800010040000000000001000000050000000000000000000000000040000000000000004000000000008e000000000000008e00000000000000000020000000000048b83c0000000000000048bf2a000000000000000f05";

let failures = 0;

/** Prints a line either way so a passing run is still legible. */
function check(name: string, condition: boolean, detail: string = ""): void {
  if (condition) {
    console.log(`  ok   ${name}`);
  } else {
    failures += 1;
    console.error(`  FAIL ${name}${detail === "" ? "" : ` - ${detail}`}`);
  }
}

function clean(hex: string): string {
  return hex.replace(/\s+/g, "");
}

console.log("fixtures agree with binary-gen (Python)");
{
  const ours = toHex(buildPrint("hello world"));
  const theirs = clean(PYTHON_HELLO_WORLD);
  check("linux_print('hello world')", ours === theirs, `\n    ts: ${ours}\n    py: ${theirs}`);

  const ourExit = toHex(buildExit(42));
  const theirExit = clean(PYTHON_EXIT_42);
  check("linux_exit(42)", ourExit === theirExit, `\n    ts: ${ourExit}\n    py: ${theirExit}`);
}

console.log("inspector accepts a correct binary");
{
  check(
    "accepts surrounding whitespace before the hex prefix",
    inspect(` \n0x${PYTHON_HELLO_WORLD}\n `).stage === "sound",
  );
  const report = inspect(clean(PYTHON_HELLO_WORLD));
  check("reaches the sound stage", report.stage === "sound", `got ${report.stage}`);

  if (report.stage === "sound") {
    const { image } = report;
    check("decodes 8 instructions", image.instructions.length === 8);
    check("recovers the payload", image.dataText === "hello world\\n", `got ${image.dataText}`);
    check(
      "write length matches",
      image.notes.some((note) => note.kind === "write-length-ok"),
    );
    check(
      "string pointer resolves",
      image.notes.some((note) => note.kind === "string-pointer-ok"),
    );
    check("entry is 0x400078", image.header.entry === 0x400078);
    check("one PT_LOAD, R-X", image.segments.length === 1 && image.segments[0]?.flags === "R-X");
  }
}

console.log("inspector reads an exit-only binary");
{
  const report = inspect(clean(PYTHON_EXIT_42));
  check("reaches the sound stage", report.stage === "sound");

  if (report.stage === "sound") {
    check("no data payload", report.image.dataOffset === null);
    check(
      "exit code 42 in rdi",
      report.image.instructions.some(
        (i) => i.mnemonic === "mov" && i.register === "rdi" && i.immediate === 42,
      ),
    );
    check("no write-length claim to check", report.image.notes.length === 0);
  }
}

console.log("inspector catches the injected flaws");
{
  const offByOne = inspect(toHex(buildPrint("hello world", 0, "write-length")));
  check(
    "off-by-one write length is flagged",
    offByOne.stage === "sound" &&
      offByOne.image.notes.some((note) => note.kind === "write-length-mismatch"),
  );

  const badMagic = inspect(toHex(buildPrint("hello world", 0, "bad-magic")));
  check("corrupt magic fails at structure", badMagic.stage === "structure");

  const truncated = inspect(toHex(buildPrint("hello world", 0, "truncated")));
  check(
    "truncated output still parses as ELF but loses the payload",
    truncated.stage === "sound" && truncated.image.dataText !== "hello world\\n",
  );
}

console.log("inspector rejects unusable hex");
{
  check("odd length", inspect("7f454c460").stage === "hex");
  check("non-hex characters", inspect("7f454c4g").stage === "hex");
  check("empty", inspect("   ").stage === "hex");
  check("not an ELF at all", inspect("deadbeefdeadbeef".repeat(8)).stage === "structure");
}

if (failures > 0) {
  console.error(`\n${failures} check(s) failed`);
  process.exit(1);
}

console.log("\nall checks passed");
