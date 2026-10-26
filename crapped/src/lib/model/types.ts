/** Share inference targets and worker messages without importing the runtime. */

import type { GgufSource } from "./gguf-source";

/** Where inference runs. */
type Device = "webgpu" | "wasm";

/** A model source and an explicitly chosen compute device. */
interface GgufConfig {
  readonly kind: "gguf";
  readonly source: GgufSource;
  readonly device: Device;
  readonly maxNewTokens: number;
}

/** A load request always carries the source its backend requires. */
type LoadConfig = { readonly kind: "stub"; readonly maxNewTokens: number } | GgufConfig;

/** UI selection; files can be unselected and an edited URL can be invalid. */
type ModelConfig =
  | Exclude<LoadConfig, GgufConfig>
  | (Omit<GgufConfig, "source"> & {
      readonly source: GgufSource | null;
    });

/** A defect the stub can introduce, so the inspector's warnings show without a model. */
type Flaw = "none" | "write-length" | "bad-magic" | "truncated";

/** Initialization status; progress is unknown while the native runtime loads. */
interface LoadStatus {
  /** Current file or initialization step. */
  readonly file: string;
  /** Fraction complete in `[0, 1]`, or `null` when the total size is unknown. */
  readonly fraction: number | null;
  readonly loadedBytes: number;
  readonly totalBytes: number;
}

/** Whether a URL's shards are stored complete in this browser's model cache. */
type CacheState = "cached" | "partial" | "absent" | "unknown";

/** Correlates a generate request with the events it produces. */
type RequestId = number;

/** Main thread → worker. */
type Command =
  | { readonly kind: "load"; readonly config: LoadConfig; readonly flaw: Flaw }
  | { readonly kind: "generate"; readonly id: RequestId; readonly prompt: string }
  | { readonly kind: "cancel" };

/** Worker → main thread. */
type Event =
  | { readonly kind: "progress"; readonly status: LoadStatus }
  | { readonly kind: "ready"; readonly config: LoadConfig }
  | { readonly kind: "chunk"; readonly id: RequestId; readonly text: string }
  | { readonly kind: "done"; readonly id: RequestId; readonly text: string }
  | { readonly kind: "failed"; readonly id: RequestId | null; readonly message: string };

/**
 * Load once, generate many, cancel in flight. The stub and the GGUF runtime
 * both implement it, so fixtures exercise the real worker protocol.
 */
interface Backend {
  /** @throws If files, memory or the requested compute device are unavailable. */
  load(onProgress: (status: LoadStatus) => void): Promise<void>;

  /** Streams to `onChunk` and resolves with the complete text. */
  generate(prompt: string, onChunk: (text: string) => void): Promise<string>;

  /** Ask an in-flight {@link generate} to stop early. Safe to call when idle. */
  cancel(): void;
}

export {
  type Backend,
  type CacheState,
  type Command,
  type Device,
  type Event,
  type Flaw,
  type GgufConfig,
  type LoadConfig,
  type LoadStatus,
  type ModelConfig,
  type RequestId,
};
