/**
 * Worker that reports whether a model URL is already in wllama's cache.
 *
 * Separate from the inference worker so the page can ask before any load
 * without creating a runtime. It only reads the cache; it never downloads.
 */

import { CacheManager, ModelManager, POLYFILL_ETAG } from "@wllama/wllama";

import type { CacheState } from "./types";

self.addEventListener("message", (message: MessageEvent<string>) => {
  void probe(message.data).then(
    (state) => self.postMessage(state),
    () => self.postMessage("unknown" satisfies CacheState),
  );
});

/**
 * Whether every shard of `url` is stored at its full downloaded size.
 *
 * A cancelled or capped download can leave a short file behind. wllama writes
 * metadata only after a download completes, and its `getMetadata()` invents
 * metadata for a file without any, so a polyfilled entry counts as partial.
 */
async function probe(url: string): Promise<CacheState> {
  const cache = new CacheManager();
  const urls: string[] = ModelManager.parseModelUrl(url);
  let found = 0;

  for (const shard of urls) {
    const name = await cache.getNameFromURL(shard);
    const metadata = await cache.getMetadata(name);
    if (metadata === null) {
      continue;
    }
    found += 1;
    const size = await cache.getSize(name);
    if (metadata.etag === POLYFILL_ETAG || size <= 0 || size !== metadata.originalSize) {
      return "partial";
    }
  }

  return found === urls.length ? "cached" : found === 0 ? "absent" : "partial";
}
