/**
 * Public surface of the model library: select a URL or local files, load, generate.
 *
 * Runtime imports belong in the worker, so rendering the page neither starts
 * inference nor puts the runtime in the main-thread bundle.
 */

export { probeCache } from "./cache";
export { ModelClient, type ClientHandlers } from "./client";
export { readGgufSource, readGgufUrl } from "./gguf-source";
export {
  type CacheState,
  type Device,
  type Flaw,
  type LoadStatus,
  type LoadConfig,
  type ModelConfig,
} from "./types";
