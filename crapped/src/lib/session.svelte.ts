/**
 * The demo's state machine and imperative shell: it owns the worker, the timers
 * and the transitions. A tagged {@link Phase} rather than booleans, so states
 * like a report with no bytes behind it can't be built.
 */

import { inspect, saveBytes, type Inspection } from "./elf";
import {
  ModelClient,
  type Flaw,
  type LoadStatus,
  type ModelConfig,
  type LoadConfig,
} from "./model";
import { DEFAULT_CONFIG } from "./config";

type Phase =
  | { readonly kind: "cold" }
  | { readonly kind: "loading"; readonly status: LoadStatus | null }
  | { readonly kind: "ready"; readonly loadElapsedMs: number }
  | { readonly kind: "generating"; readonly hex: string; readonly startedAt: number }
  | {
      readonly kind: "settled";
      readonly hex: string;
      readonly inspection: Inspection;
      readonly elapsedMs: number;
      /** True when the user stopped it rather than the model finishing. */
      readonly cancelled: boolean;
    }
  | { readonly kind: "broken"; readonly message: string };

/** One per page. The worker starts on first {@link load}, so idle visitors pay nothing. */
class Session {
  phase = $state<Phase>({ kind: "cold" });

  /** Used by the next {@link load}. */
  config = $state<ModelConfig>(DEFAULT_CONFIG);

  flaw = $state<Flaw>("none");

  prompt = $state("");

  #client: ModelClient | null = null;

  /** Set by {@link stop} and read once when the generation settles. */
  #stopRequested = false;

  get canGenerate(): boolean {
    return this.phase.kind === "ready" || this.phase.kind === "settled";
  }

  /** Replace an idle selection and release the previously loaded model. */
  setConfig(config: ModelConfig): void {
    if (this.phase.kind === "loading" || this.phase.kind === "generating") {
      return;
    }

    this.dispose();
    this.config = config;
    this.phase = { kind: "cold" };
  }

  /** Change an idle fixture selection; the next load must use the new flaw. */
  setFlaw(flaw: Flaw): void {
    if (this.phase.kind === "loading" || this.phase.kind === "generating" || this.flaw === flaw) {
      return;
    }

    this.setConfig(this.config);
    this.flaw = flaw;
  }

  /** Release a model being initialized and return to file selection. */
  cancelLoad(): void {
    if (this.phase.kind !== "loading") {
      return;
    }

    this.dispose();
    this.phase = { kind: "cold" };
  }

  /** Disposes the old client rather than reusing it, so no previous model stays resident. */
  async load(): Promise<void> {
    const selection = $state.snapshot(this.config);
    let config: LoadConfig;

    if (selection.kind === "gguf") {
      if (selection.source === null) {
        this.phase = {
          kind: "broken",
          message: "Choose local GGUF files or enter a valid public model URL first.",
        };

        return;
      }

      config = { ...selection, source: selection.source };
    } else {
      config = selection;
    }

    this.#client?.dispose();
    const client = new ModelClient({
      onProgress: (status) => {
        if (this.#client === client) {
          this.phase = { kind: "loading", status };
        }
      },
      onChunk: (text) => {
        if (this.#client === client && this.phase.kind === "generating") {
          this.phase = { ...this.phase, hex: this.phase.hex + text };
        }
      },
    });
    this.#client = client;

    this.phase = { kind: "loading", status: null };
    const startedAt = performance.now();

    try {
      await client.load(config, this.flaw);
      if (this.#client === client) {
        this.phase = { kind: "ready", loadElapsedMs: performance.now() - startedAt };
      }
    } catch (cause) {
      if (this.#client === client) {
        // A failed load can leave gigabytes allocated; terminating the worker
        // is the only release that covers every runtime state.
        this.dispose();
        this.phase = { kind: "broken", message: describe(cause) };
      }
    }
  }

  /** Inspects whatever comes back, even after a stop: the report then says the image is short. */
  async generate(prompt: string): Promise<void> {
    const client = this.#client;

    if (client === null || !this.canGenerate) {
      return;
    }

    this.prompt = prompt;
    this.#stopRequested = false;
    const startedAt = performance.now();
    this.phase = { kind: "generating", hex: "", startedAt };

    try {
      const hex = await client.generate(prompt);

      if (this.#client !== client) {
        return;
      }

      this.phase = {
        kind: "settled",
        hex,
        inspection: inspect(hex),
        elapsedMs: performance.now() - startedAt,
        cancelled: this.#stopRequested,
      };
    } catch (cause) {
      if (this.#client === client) {
        this.phase = { kind: "broken", message: describe(cause) };
      }
    }
  }

  /** Ask the model to stop; the partial output is still inspected. */
  stop(): void {
    this.#stopRequested = true;
    this.#client?.cancel();
  }

  /** A no-op until the hex has parsed, so callers needn't guard it. */
  download(fileName: string = "crap.out"): void {
    if (this.phase.kind !== "settled" || this.phase.inspection.stage === "hex") {
      return;
    }

    saveBytes(this.phase.inspection.bytes, fileName);
  }

  /** Call on teardown. */
  dispose(): void {
    this.#client?.dispose();
    this.#client = null;
  }
}

function describe(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

export { Session, type Phase };
