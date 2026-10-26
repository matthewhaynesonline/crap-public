/** Ask a short-lived worker whether a model URL would load from the cache. */

import type { CacheState } from "./types";

/**
 * Resolve to the cache state of `url`'s shards; `"unknown"` when storage is
 * unavailable (private windows often block it) or the check fails.
 */
function probeCache(url: string): Promise<CacheState> {
  return new Promise((resolve) => {
    let worker: Worker;
    try {
      worker = new Worker(new URL("./cache-probe.ts", import.meta.url), { type: "module" });
    } catch {
      resolve("unknown");

      return;
    }
    const finish = (state: CacheState): void => {
      worker.terminate();
      resolve(state);
    };
    worker.addEventListener("message", (message: MessageEvent<CacheState>) => finish(message.data));
    worker.addEventListener("error", () => finish("unknown"));
    worker.postMessage(url);
  });
}

export { probeCache };
