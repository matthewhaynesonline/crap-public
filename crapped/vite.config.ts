import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

/**
 * SharedArrayBuffer and threaded WASM need cross-origin isolation. The Space
 * README's `custom_headers` send these in production.
 */
const ISOLATION_HEADERS = {
  "Cross-Origin-Opener-Policy": "same-origin",
  "Cross-Origin-Embedder-Policy": "require-corp",
};

/**
 * Vite config for the CRAP browser demo.
 *
 * Keep the inference worker separate from the main-thread bundle.
 */
export default defineConfig({
  base: "./",
  plugins: [svelte()],

  worker: {
    // The inference worker is constructed with `type: "module"`, so its bundle
    // has to be ESM as well.
    format: "es",
  },

  server: { headers: ISOLATION_HEADERS },
  preview: { headers: ISOLATION_HEADERS },
});
