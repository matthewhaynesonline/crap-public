import {
  CacheManager,
  ModelManager,
  Wllama,
  WllamaAbortError,
  type ChatCompletionChunk,
  type ChatCompletionParams,
  type LoadModelParams,
  type StreamParams,
} from "@wllama/wllama";
import wasmUrl from "@wllama/wllama/esm/wasm/wllama.wasm?url";

import { incompleteModelFiles } from "./cache-entries";
import { SYSTEM_PROMPT } from "./prompt";
import type { Backend, GgufConfig, LoadStatus } from "./types";

// llama.cpp consumes these server parameter names. wllama 3.8.1's
// SamplingParams types still use the older penalty_* names.
type BinaryCompletionParams = ChatCompletionParams &
  StreamParams<ChatCompletionChunk> & {
    readonly repeat_penalty: number;
    readonly presence_penalty: number;
    readonly frequency_penalty: number;
  };

const LARGE_FILE_BYTES = 2 ** 31;
const LARGE_FILE_MESSAGE =
  "This browser cannot stream GGUF files over 2 GiB. Try a current Chromium browser.";

/** Run a public download or local GGUF through llama.cpp in this browser. */
class GgufBackend implements Backend {
  readonly #config: GgufConfig;
  #runtime: Wllama | null = null;
  #abort: AbortController | null = null;

  constructor(config: GgufConfig) {
    this.#config = config;
  }

  /** Cache URL downloads, then initialize the model with the selected device. */
  async load(onProgress: (status: LoadStatus) => void): Promise<void> {
    if (!self.crossOriginIsolated) {
      throw new Error(
        "GGUF inference requires cross-origin isolation. Use the Vite server or configure COOP/COEP headers.",
      );
    }

    // The JSPI path reads tensors on demand. The legacy mmap path copies an
    // entire file into WASM memory and cannot handle these larger tensors.
    const canStreamLargeFiles = "Suspending" in WebAssembly;
    if (
      !canStreamLargeFiles &&
      this.#config.source.kind === "local" &&
      this.#config.source.files.some((file) => file.size >= LARGE_FILE_BYTES)
    ) {
      throw new Error(LARGE_FILE_MESSAGE);
    }

    let nativeError = "";
    const runtime = new Wllama(
      { default: wasmUrl },
      {
        logger: {
          ...console,
          error: (...details: unknown[]) => {
            const message = details.map(String).join(" ");
            if (!message.startsWith("Stack trace")) {
              nativeError = message;
            }
            console.error(...details);
          },
        },
      },
    );
    // Package assets stay local. Unsupported browsers report a failure instead
    // of fetching a compatibility runtime from an unpinned CDN.
    runtime.setCompat(null);

    if (this.#config.device === "webgpu" && !runtime.isSupportWebGPU()) {
      throw new Error(
        "WebGPU is unavailable in this browser. Choose WASM CPU or use a WebGPU-capable browser.",
      );
    }

    const source = this.#config.source;
    onProgress({
      file:
        source.kind === "url" ? "Checking model cache…" : `Initializing ${this.#config.device}…`,
      fraction: null,
      loadedBytes: 0,
      totalBytes: source.kind === "local" ? source.totalBytes : 0,
    });

    const params: LoadModelParams = {
      n_gpu_layers: this.#config.device === "webgpu" ? 99999 : 0,
      n_ctx: this.#config.maxNewTokens + 512,
      n_batch: 128,
      n_ubatch: 128,
      n_parallel: 1,
      jinja: true,
      reasoning: false,
      default_template_kwargs: { enable_thinking: false },
    };

    // A URL's size is known only once the download starts, so stop there
    // rather than after gigabytes have been fetched and cached. Progress sums
    // every shard, and the limit is per file, so split models are left to the
    // runtime, as local shards are.
    const download = new AbortController();
    let oversized = false;

    try {
      if (source.kind === "url") {
        await pruneIncompleteModels();
        await runtime.loadModelFromUrl(source.url, {
          ...params,
          useCache: true,
          signal: download.signal,
          progressCallback: ({ loaded, total }) => {
            if (!canStreamLargeFiles && !source.split && total >= LARGE_FILE_BYTES) {
              oversized = true;
              download.abort();

              return;
            }
            const complete = total > 0 && loaded >= total;
            onProgress({
              file: complete ? `Initializing ${this.#config.device}…` : "Downloading model…",
              fraction: total > 0 && !complete ? Math.min(1, loaded / total) : null,
              loadedBytes: loaded,
              totalBytes: total,
            });
          },
        });
      } else {
        await runtime.loadModel([...source.files], params);
      }

      // wllama can resolve after llama.cpp rejects an incomplete cache file.
      if (nativeError !== "" || !runtime.isModelLoaded()) {
        throw new Error(
          "The model did not load completely. The browser may have run out of storage for one file. Try a split GGUF or a browser with more storage.",
        );
      }
    } catch (cause) {
      // exit() also releases workers created by an incomplete initialization.
      await runtime.exit();
      if (oversized) {
        throw new Error(LARGE_FILE_MESSAGE);
      }
      const reason = cause instanceof Error ? cause.message : String(cause);
      // Private windows (Firefox's, for one) refuse the origin file system
      // wllama caches into, before any download starts.
      if (source.kind === "url" && /getDirectory/i.test(reason)) {
        throw new Error(
          "This browser blocks model storage here (private windows often do). Try a normal window in Chrome.",
        );
      }
      const context =
        source.kind === "url"
          ? " Model downloads need a public URL, CORS access and enough browser storage."
          : "";
      const message =
        nativeError === "" ? reason : `${reason.replace(/[.:]+$/, "")}: ${nativeError}`;

      throw new Error(
        (context === "" || /[.!?]$/.test(message) ? message : `${message}.`) + context,
      );
    }

    this.#runtime = runtime;
  }

  /** Stream one independent request using the model's own chat template. */
  async generate(prompt: string, onChunk: (text: string) => void): Promise<string> {
    const runtime = this.#runtime;

    if (runtime === null) {
      throw new Error("generate() called before the GGUF finished loading");
    }

    const abort = new AbortController();
    this.#abort = abort;
    let completion = "";

    try {
      const request: BinaryCompletionParams = {
        messages: [
          { role: "system", content: SYSTEM_PROMPT },
          { role: "user", content: prompt },
        ],
        max_tokens: this.#config.maxNewTokens,
        temperature: 0,
        top_k: 1,
        repeat_penalty: 1,
        presence_penalty: 0,
        frequency_penalty: 0,
        chat_template_kwargs: { enable_thinking: false },
        abortSignal: abort.signal,
        stream: true,
        onData: (chunk) => {
          const text = chunk.choices[0]?.delta.content ?? "";
          completion += text;
          onChunk(text);
        },
      };

      await runtime.createChatCompletion(request);
    } catch (cause) {
      if (abort.signal.aborted) {
        return completion;
      }
      const reason = cause instanceof Error ? cause.message : String(cause);
      if (cause instanceof WllamaAbortError || /\babort(?:ed)?\b/i.test(reason)) {
        throw new Error(
          "Generation stopped because the model runtime aborted. Reload the model and try again; if it continues, try a split GGUF or a browser with more storage and memory.",
        );
      }

      throw cause;
    } finally {
      this.#abort = null;
    }

    return completion;
  }

  /** Stop generation while retaining the partial hex for inspection. */
  cancel(): void {
    this.#abort?.abort();
  }
}

/**
 * Delete interrupted downloads that would make every cached load throw.
 *
 * See {@link incompleteModelFiles}. Runs inside `load()`'s error handling, so
 * a browser that blocks storage gets the same message as before.
 */
async function pruneIncompleteModels(): Promise<void> {
  const cache = new CacheManager();
  const incomplete = new Set(
    incompleteModelFiles(await cache.list(), (url) => ModelManager.parseModelUrl(url)),
  );
  if (incomplete.size > 0) {
    await cache.deleteMany((file) => incomplete.has(file.name));
  }
}

export { GgufBackend };
