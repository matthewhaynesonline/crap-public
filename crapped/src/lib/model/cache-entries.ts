/**
 * Find cached model files that would break wllama's cache lookup.
 *
 * wllama 3.8.1 writes a shard's metadata only once that shard finishes
 * downloading. A cached load calls its `getModels()`, which builds a model for
 * every cached first shard with metadata. That constructor throws "Model file
 * not found" when a later shard has no metadata, before wllama's own validity
 * filter runs. So a split download interrupted after its first shard makes
 * every later load fail, for any URL and across reloads, until the visitor
 * clears site data. Deleting the interrupted model's files first lets the next
 * load download it again.
 *
 * Pure: the caller lists the cache and deletes what this returns.
 */

/** The fields of a wllama `CacheEntry` this check reads. */
interface CachedFile {
  readonly name: string;
  readonly size: number;
  readonly metadata: { readonly originalURL: string; readonly originalSize: number };
}

/**
 * Names of the cached files that belong to an incompletely downloaded model.
 *
 * A model is complete when every shard URL has a cached file with metadata and
 * the file is as large as the download was. For an incomplete model, this
 * returns its files that have metadata. Files without metadata are invisible
 * to wllama's lookup, and its next download of that URL truncates them.
 *
 * A later shard whose first shard has no metadata is left alone. wllama only
 * looks up models from their first shard, so it can't trigger the throw.
 *
 * @param files - Every cached file, as `CacheManager.list()` returns them.
 *   wllama gives a file without metadata an empty `originalURL`.
 * @param shardUrls - Expands a first-shard URL to every shard URL. Pass
 *   `ModelManager.parseModelUrl` so the grouping matches wllama's.
 * @returns File names to delete; empty when every cached model is complete.
 */
function incompleteModelFiles(
  files: readonly CachedFile[],
  shardUrls: (url: string) => readonly string[],
): readonly string[] {
  const byUrl = new Map(
    files
      .filter((file) => file.metadata.originalURL !== "")
      .map((file) => [file.metadata.originalURL, file]),
  );
  const incomplete: string[] = [];

  for (const url of byUrl.keys()) {
    const shards = shardUrls(url);
    if (shards[0] !== url) {
      continue;
    }
    const cached = shards.map((shard) => byUrl.get(shard));
    const complete = cached.every(
      (shard) => shard !== undefined && shard.size === shard.metadata.originalSize,
    );
    if (!complete) {
      incomplete.push(...cached.flatMap((shard) => (shard === undefined ? [] : [shard.name])));
    }
  }

  return incomplete;
}

export { incompleteModelFiles, type CachedFile };
