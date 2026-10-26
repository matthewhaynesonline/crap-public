import assert from "node:assert/strict";

import { GgufBackend } from "./gguf";
import { readGgufSource, readGgufUrl } from "./gguf-source";
import type { GgufConfig } from "./types";
import { CacheManager, Wllama } from "./wllama.check";

Object.defineProperty(globalThis, "self", { value: { crossOriginIsolated: true } });

const url = readGgufUrl("http://127.0.0.1:8085/model.gguf");
assert(url.ok);
const header = new Uint8Array(24);
header.set(new TextEncoder().encode("GGUF"));
new DataView(header.buffer).setUint32(4, 3, true);
const local = await readGgufSource([new File([header], "model.gguf")]);
assert(local.ok);

for (const source of [url.value, local.value]) {
  const config: GgufConfig = { kind: "gguf", source, device: "webgpu", maxNewTokens: 2048 };
  for (const scenario of ["native-error", "unloaded"] as const) {
    Wllama.scenario = scenario;
    const backend = new GgufBackend(config);
    const exits = Wllama.exits;
    await assert.rejects(
      backend.load(() => {}),
      (cause: unknown) =>
        cause instanceof Error &&
        /did not load completely.*storage/.test(cause.message) &&
        !cause.message.includes(".:"),
    );
    assert.equal(Wllama.exits, exits + 1);
    await assert.rejects(
      backend.generate("exit 42", () => {}),
      /before.*loading/,
    );
    Wllama.scenario = "ready";
    await backend.load(() => {});
    assert.equal(await backend.generate("exit 42", () => {}), "7f454c46");
    assert.equal(Wllama.exits, exits + 1);
  }

  Wllama.scenario = "ready";
  const backend = new GgufBackend(config);
  await backend.load(() => {});
  assert.equal(await backend.generate("exit 42", () => {}), "7f454c46");

  Wllama.completion = "abort";
  await assert.rejects(
    backend.generate("exit 42", () => {}),
    /runtime aborted.*Reload/,
  );

  // Stop must preserve streamed output regardless of the runtime's error shape.
  for (const completion of ["ready", "abort", "error", "non-error"] as const) {
    Wllama.completion = completion;
    assert.equal(await backend.generate("exit 42", () => backend.cancel()), "7f454c46");
  }

  Wllama.completion = "error";
  await assert.rejects(
    backend.generate("exit 42", () => {}),
    /^Error: unrelated failure$/,
  );
  Wllama.completion = "ready";
}

Wllama.scenario = "fetch-error";
const exits = Wllama.exits;
await assert.rejects(
  new GgufBackend({ kind: "gguf", source: url.value, device: "webgpu", maxNewTokens: 2048 }).load(
    () => {},
  ),
  /HTTP 404.*public URL, CORS/,
);
assert.equal(Wllama.exits, exits + 1);

// A split download interrupted after its first shard must not break later
// loads of any URL: here, a different single-file model.
const otherModel = "http://127.0.0.1:8085/other.gguf";
CacheManager.files = [
  {
    name: "a_model-00001-of-00002.gguf",
    size: 10,
    metadata: { originalURL: "http://127.0.0.1:8085/model-00001-of-00002.gguf", originalSize: 10 },
  },
  { name: "b_model-00002-of-00002.gguf", size: 4, metadata: { originalURL: "", originalSize: 4 } },
  { name: "c_other.gguf", size: 7, metadata: { originalURL: otherModel, originalSize: 7 } },
];
Wllama.scenario = "ready";
const other = readGgufUrl(otherModel);
assert(other.ok);
await new GgufBackend({
  kind: "gguf",
  source: other.value,
  device: "webgpu",
  maxNewTokens: 2048,
}).load(() => {});
assert.deepEqual(
  CacheManager.files.map((file) => file.name),
  ["b_model-00002-of-00002.gguf", "c_other.gguf"],
);

console.log(
  "GGUF checks passed: resolved load failures, readiness, aborts, user stop, recovery, interrupted split cache",
);
