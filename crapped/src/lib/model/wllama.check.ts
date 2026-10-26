import type {
  ChatCompletionChunk,
  ChatCompletionParams,
  LoadModelParams,
  StreamParams,
} from "@wllama/wllama";

type Scenario = "ready" | "native-error" | "unloaded" | "fetch-error";
type Completion = "ready" | "abort" | "error" | "non-error";

/** Double only the runtime boundary; checks exercise the production backend. */
class Wllama {
  static scenario: Scenario = "ready";
  static completion: Completion = "ready";
  static exits = 0;
  readonly #logger: { error: (...details: unknown[]) => void };

  constructor(_paths: unknown, options: { logger: { error: (...details: unknown[]) => void } }) {
    this.#logger = options.logger;
  }

  setCompat(): void {}

  isSupportWebGPU(): boolean {
    return true;
  }

  isModelLoaded(): boolean {
    return Wllama.scenario !== "unloaded";
  }

  async loadModelFromUrl(_url: string, _params: LoadModelParams): Promise<void> {
    CacheManager.lookUpModels();
    await this.loadModel();
  }

  async loadModel(): Promise<void> {
    if (Wllama.scenario === "native-error") {
      this.#logger.error("model is corrupted or incomplete");
      this.#logger.error("Stack trace: ignored");
    }
    if (Wllama.scenario === "fetch-error") {
      throw new Error("HTTP 404");
    }
  }

  async exit(): Promise<void> {
    Wllama.exits += 1;
  }

  async createChatCompletion(
    params: ChatCompletionParams & StreamParams<ChatCompletionChunk>,
  ): Promise<void> {
    params.onData({
      id: "check",
      object: "chat.completion.chunk",
      created: 0,
      model: "check",
      choices: [{ index: 0, delta: { content: "7f454c46" }, finish_reason: null, logprobs: null }],
    });
    if (Wllama.completion === "abort") {
      throw new Error("(ABORT)");
    }
    if (Wllama.completion === "error") {
      throw new Error("unrelated failure");
    }
    if (Wllama.completion === "non-error") {
      throw "runtime stopped";
    }
    if (params.abortSignal?.aborted) {
      throw new WllamaAbortError();
    }
  }
}

class WllamaAbortError extends Error {
  constructor() {
    super("Operation aborted");
  }
}

/** A cached file as wllama 3.8.1 lists it; no metadata means an empty `originalURL`. */
interface CacheEntry {
  readonly name: string;
  readonly size: number;
  readonly metadata: { readonly originalURL: string; readonly originalSize: number };
}

/** The OPFS model cache, shared by every instance as the real one is. */
class CacheManager {
  static files: CacheEntry[] = [];

  async list(): Promise<CacheEntry[]> {
    return [...CacheManager.files];
  }

  async deleteMany(predicate: (file: CacheEntry) => boolean): Promise<void> {
    CacheManager.files = CacheManager.files.filter((file) => !predicate(file));
  }

  /**
   * Reproduce wllama 3.8.1's cached lookup (`getModels()` and `getAllFiles()`):
   * any first shard with metadata whose later shard has none throws, whatever
   * URL is being loaded.
   */
  static lookUpModels(): void {
    for (const file of CacheManager.files) {
      const url = file.metadata.originalURL;
      const shards = ModelManager.parseModelUrl(url);
      if (url === "" || shards[0] !== url) {
        continue;
      }
      for (const shard of shards) {
        if (!CacheManager.files.some((other) => other.metadata.originalURL === shard)) {
          throw new Error(`Model file not found: ${shard}`);
        }
      }
    }
  }
}

/** wllama 3.8.1's shard expansion, for split URLs without a query string. */
class ModelManager {
  static parseModelUrl(url: string): string[] {
    const match = url.match(/-(\d{5})-of-(\d{5})\.gguf$/);
    if (match === null) {
      return [url];
    }
    const base = url.slice(0, match.index);
    const total = match[2] ?? "";

    return Array.from(
      { length: Number(total) },
      (_, index) => `${base}-${String(index + 1).padStart(5, "0")}-of-${total}.gguf`,
    );
  }
}

export { CacheManager, ModelManager, Wllama, WllamaAbortError };
