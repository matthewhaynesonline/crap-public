import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";

import { incompleteModelFiles, type CachedFile } from "./cache-entries";
import { readGgufSource, readGgufUrl } from "./gguf-source";
import { SYSTEM_PROMPT } from "./prompt";

function file(name: string, version: number = 3): File {
  const header = new Uint8Array(24);
  header.set(new TextEncoder().encode("GGUF"));
  new DataView(header.buffer).setUint32(4, version, true);

  return new File([header], name);
}

const standalone = await readGgufSource([file("model.gguf")]);
assert(standalone.ok);
assert.equal(standalone.value.files.length, 1);
assert.equal(standalone.value.totalBytes, 24);

for (const url of [
  "https://huggingface.co/owner/model/resolve/main/model.gguf",
  "https://huggingface.co/owner/model/resolve/abc123/model-00001-of-00004.gguf",
  "http://127.0.0.1:8085/model.gguf",
  "http://localhost/model.gguf",
  "http://[::1]/model.gguf",
]) {
  const source = readGgufUrl(` ${url} `);
  assert(source.ok);
  assert.equal(source.value.url, url);
  assert.equal(structuredClone(source.value).kind, "url");
  assert.equal(source.value.split, url.includes("-of-"));
}

for (const invalid of [
  "model.gguf",
  "http://example.com/model.gguf",
  "file:///tmp/model.gguf",
  "https://user:password@example.com/model.gguf",
  "https://example.com/model.gguf?token=secret",
  "https://example.com/model.gguf#fragment",
  "https://example.com/model.safetensors",
  "https://huggingface.co/owner/model/blob/main/model.gguf",
  "https://example.com/model-00002-of-00004.gguf",
  "https://example.com/model-00001-of-00000.gguf",
]) {
  assert.equal(readGgufUrl(invalid).ok, false, invalid);
}

const ordered = await readGgufSource([
  file("model-00002-of-00002.gguf"),
  file("model-00001-of-00002.gguf"),
]);
assert(ordered.ok);
assert.equal(ordered.value.files[0].name, "model-00001-of-00002.gguf");

for (const invalid of [
  [],
  [file("model-00001-of-00002.gguf")],
  [file("model-00001-of-00002.gguf"), file("model-00001-of-00002.gguf")],
  [file("model-00001-of-00002.gguf"), file("other-00002-of-00002.gguf")],
  [file("one.gguf"), file("two.gguf")],
  [new File(["not a model"], "bad.gguf")],
  [file("unsupported.gguf", 99)],
]) {
  assert.equal((await readGgufSource(invalid)).ok, false);
}

/** A cached file; `downloaded` is the full size, or null for no metadata yet. */
function cached(url: string, size: number, downloaded: number | null): CachedFile {
  return {
    name: `hash_${url.split("/").pop() ?? ""}`,
    size,
    metadata: { originalURL: downloaded === null ? "" : url, originalSize: downloaded ?? size },
  };
}

function shardUrls(url: string): readonly string[] {
  const total = url.match(/-\d{5}-of-(\d{5})\.gguf$/)?.[1];
  if (total === undefined) {
    return [url];
  }

  return Array.from({ length: Number(total) }, (_, index) =>
    url.replace(/-\d{5}-of-/, `-${String(index + 1).padStart(5, "0")}-of-`),
  );
}

const first = "https://example.com/m-00001-of-00002.gguf";
const second = "https://example.com/m-00002-of-00002.gguf";
const single = "https://example.com/single.gguf";
for (const [files, expected] of [
  [[], []],
  [[cached(first, 10, 10), cached(second, 5, 5)], []],
  [[cached(single, 3, 3)], []],
  // The poisoning case: the first shard finished, the second never got metadata.
  [[cached(first, 10, 10), cached(second, 2, null)], ["hash_m-00001-of-00002.gguf"]],
  [[cached(first, 10, 10)], ["hash_m-00001-of-00002.gguf"]],
  [
    [cached(first, 10, 10), cached(second, 2, 5)],
    ["hash_m-00001-of-00002.gguf", "hash_m-00002-of-00002.gguf"],
  ],
  [[cached(single, 1, 3)], ["hash_single.gguf"]],
  [[cached(single, 3, 3), cached(first, 10, 10)], ["hash_m-00001-of-00002.gguf"]],
  // wllama never looks up a model from a later shard, so an orphan is harmless.
  [[cached(second, 5, 5)], []],
] satisfies [CachedFile[], string[]][]) {
  assert.deepEqual(incompleteModelFiles(files, shardUrls), expected);
}

// The training prompt is the contract. A locally plausible substitute can
// turn a runtime integration error into an apparent model failure. npm runs
// scripts from the package root; `training/` is a private submodule, so public
// checkouts skip this comparison and say so.
const trainingPath = "../training/src/training/training_utils.py";
let promptCheck = "canonical training prompt";
if (existsSync(trainingPath)) {
  const training = readFileSync(trainingPath, "utf8");
  const definition = training.match(/SYSTEM_PROMPT = \(([\s\S]*?)\n\)/)?.[1];
  assert(definition !== undefined);
  const canonical = [...definition.matchAll(/"([^"]*)"/g)].map((match) => match[1]).join("");
  assert.equal(SYSTEM_PROMPT, canonical);
} else {
  promptCheck = `SKIPPED training prompt (${trainingPath} not present)`;
}

console.log(`model checks passed: public URLs, headers, complete shards, ${promptCheck}`);
