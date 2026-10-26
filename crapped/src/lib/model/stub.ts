/**
 * The inspector-fixtures backend. Only an explicit choice selects it, the UI
 * labels it, and a model failure never falls back to it.
 */

import { toHex } from "../elf/hex";
import { buildExit, buildPrint } from "./fixtures";
import type { Backend, Flaw, LoadStatus } from "./types";

/** Hex characters per tick, roughly one token's worth. */
const CHARS_PER_TICK = 4;

/** Slow enough to read, fast enough not to annoy. */
const TICK_MS = 12;

type Intent =
  | { readonly kind: "print"; readonly message: string; readonly exitCode: number }
  | { readonly kind: "exit"; readonly exitCode: number };

class StubBackend implements Backend {
  readonly #flaw: Flaw;
  #cancelled = false;

  constructor(flaw: Flaw = "none") {
    this.#flaw = flaw;
  }

  async load(onProgress: (status: LoadStatus) => void): Promise<void> {
    onProgress({ file: "Inspector fixtures", fraction: 1, loadedBytes: 0, totalBytes: 0 });
  }

  /**
   * Builds the whole binary, then dribbles it out; the UI can't tell the
   * difference. Resolves with what was emitted if cancelled.
   */
  async generate(prompt: string, onChunk: (text: string) => void): Promise<string> {
    this.#cancelled = false;

    const intent = readIntent(prompt);
    const bytes =
      intent.kind === "print"
        ? buildPrint(intent.message, intent.exitCode, this.#flaw)
        : buildExit(intent.exitCode, this.#flaw);

    const hex = toHex(bytes);
    let emitted = "";

    for (let at = 0; at < hex.length; at += CHARS_PER_TICK) {
      if (this.#cancelled) {
        break;
      }

      await sleep(TICK_MS);

      const chunk = hex.slice(at, at + CHARS_PER_TICK);
      emitted += chunk;
      onChunk(chunk);
    }

    return emitted;
  }

  cancel(): void {
    this.#cancelled = true;
  }
}

/**
 * Deliberately crude: quoted text means print, a number after "exit" means that
 * exit code, and anything else falls back to hello world rather than failing.
 */
function readIntent(prompt: string): Intent {
  const quoted = prompt.match(/['"“”]([^'"“”]+)['"“”]/);
  const exitCode = prompt.match(/exit(?:s|ing)?\s+(?:with\s+)?(?:code\s+)?(\d{1,3})/i);
  const code = exitCode === undefined || exitCode === null ? 0 : clampExit(Number(exitCode[1]));

  if (quoted !== null) {
    return { kind: "print", message: quoted[1]!, exitCode: code };
  }

  if (exitCode !== null) {
    return { kind: "exit", exitCode: code };
  }

  return { kind: "print", message: "hello world", exitCode: 0 };
}

/** Linux exit statuses are 0 to 255. */
function clampExit(value: number): number {
  return Number.isFinite(value) ? Math.min(255, Math.max(0, Math.trunc(value))) : 0;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export { StubBackend };
