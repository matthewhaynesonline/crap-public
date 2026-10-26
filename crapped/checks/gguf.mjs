import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";

const outfile = "node_modules/.tmp/gguf-check.mjs";
await build({
  entryPoints: ["src/lib/model/gguf.check.ts"],
  bundle: true,
  platform: "node",
  format: "esm",
  outfile,
  plugins: [
    {
      name: "runtime-double",
      setup(builder) {
        builder.onResolve({ filter: /^@wllama\/wllama$/ }, () => ({
          path: resolve("src/lib/model/wllama.check.ts"),
        }));
        builder.onResolve({ filter: /wllama\.wasm\?url$/ }, () => ({
          path: "unused-wasm",
          namespace: "check",
        }));
        builder.onLoad({ filter: /.*/, namespace: "check" }, () => ({
          contents: 'export default "unused-wasm";',
        }));
      },
    },
  ],
});
await import(pathToFileURL(resolve(outfile)).href);
