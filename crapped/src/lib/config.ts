/** Choose defaults in the app shell; the model client accepts resolved targets. */
import { readGgufUrl, type ModelConfig } from "./model";

/** Leave headroom beyond the few hundred tokens used by the checked samples. */
const MAX_NEW_TOKENS = 2048;

/** Override at build time to pin the public release's model revision; empty means unset. */
const MODEL_URL: string =
  import.meta.env.VITE_MODEL_URL ||
  "https://huggingface.co/matthewhaynesonline/gemma-4-E2B-it-crap-1.1-gguf/resolve/main/gemma-4-E2B-it-crap-1_1-Q6_K.gguf";
const modelSource = readGgufUrl(MODEL_URL);
if (!modelSource.ok) {
  throw new Error(`Invalid VITE_MODEL_URL: ${modelSource.error}`);
}

/** Downloads begin only when the visitor presses the load button. */
const DEFAULT_CONFIG: ModelConfig = {
  kind: "gguf",
  source: modelSource.value,
  device: "webgpu",
  maxNewTokens: MAX_NEW_TOKENS,
};

export { DEFAULT_CONFIG, MAX_NEW_TOKENS, MODEL_URL };
