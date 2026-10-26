---
title: CRAP Primary Education Demo
emoji: 💩
colorFrom: yellow
colorTo: gray
sdk: static
app_file: dist/index.html
app_build_command: npm ci && npm run build
models:
  - matthewhaynesonline/gemma-4-E2B-it-crap-1.1-gguf
custom_headers:
  cross-origin-opener-policy: same-origin
  cross-origin-embedder-policy: require-corp
  cross-origin-resource-policy: cross-origin
---

# CRAPPED: CRAP Primary Education Demo

A browser demo for [CRAP](https://github.com/matthewhaynesonline/crap-public). Svelte 5, Vite and [wllama](https://github.com/ngxson/wllama), with inference in a worker.

## Run locally

Use the Node version in `.nvmrc` and npm 10.9.0:

```bash
npm ci
npm run dev
```

Click **Download & load model**, then pick a sample prompt. The first load downloads ~3.6 GiB of Q6_K weights into the browser's persistent cache; later loads reuse it until site data is cleared or the browser evicts it. Inference runs on the visitor's computer, with no server GPU or Hugging Face token.

The default is the v1.1 GGUF repository over WebGPU. To use other weights, open **Advanced settings** and either:

- choose **Local GGUF files** and select every shard together (files stay on this computer), or
- set **Model URL** to an HTTPS URL ending in `.gguf` (plain HTTP works only on localhost).
  - The server must allow CORS GET/HEAD and expose `Content-Length`. For a split GGUF, use the first shard's URL; wllama fetches the rest.

To make local shards, split a downloaded Q6_K GGUF with [`llama-gguf-split`](https://github.com/ggml-org/llama.cpp/blob/master/tools/gguf-split/README.md):

```bash
llama-gguf-split --split-max-size 1500M \
  /path/to/gemma-4-E2B-it-crap-1_1-Q6_K.gguf \
  /tmp/crapped-q6
```

Since the splitter never cuts a given tensor, a shard can exceed the requested size.

Browser inference is experimental. Q6_K on WebGPU matched native llama.cpp on one exit code prompt and one print prompt. Q4_K_M produced invalid binaries in native and browser checks. Q8_0 matched F16 on the two native prompts but failed browser file reads, likely because its largest tensor (~2.5 GB) can't be split below 2 GiB. Q6_K CPU initialization ran out of memory in the tested configuration.

To try the inspector without a model, choose **Inspector fixtures (no model)** under **Advanced settings**.

## Check and build

```bash
npm run verify
npm run preview
```

`check:elf` tests the inspector against binary-gen reference bytes.
`check:model` checks public download URLs, GGUF headers, complete shard selection and runtime failure handling with a test double. When the private
`training` submodule is present it also compares the system prompt; public checkouts skip that comparison. Both run offline without model weights.

## Hosting and browser limits

For a **Hugging Face static Space**, copy the contents of `crapped/` to the Space repository root. The YAML at the top of this README builds `dist/index.html` and sets the isolation headers, using HF's [static build and custom-header support](https://huggingface.co/docs/hub/en/spaces-config-reference). If the Space's surrounding iframe blocks isolation or WebGPU, open its direct `*.hf.space` URL.

**GitHub Pages** is not tested / supported.

Development and preview serve the headers directly:

```text
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
```

Pin the model URL to a Hugging Face commit when publishing a release:

```bash
VITE_MODEL_URL=https://huggingface.co/OWNER/REPO/resolve/COMMIT/MODEL.gguf npm run build
```

Use a current Chromium browser for the tested GGUF path. Large individual tensors can hit browser allocation limits even when the model is split into shards.

The loader uses the canonical training system prompt, the GGUF chat template, greedy decoding, disabled reasoning and a repetition penalty of 1.0. Changing the prompt or sampling settings can change the bytes.

The inspector checks **hex**, **ELF structure** and static consistency: the `write` byte count and the address resolved by `lea rsi`. A browser can't run a Linux ELF, so it can't verify behavior. **Passing the inspector doesn't prove the program actually runs as expected.**

## Layout

```text
src/lib/
├── elf/               hex, x86 decoding, ELF inspection and download
├── model/             GGUF downloads/runtime, fixtures and worker protocol
├── components/        Svelte views
├── config.ts          application defaults
├── prompts.ts         sample requests
└── session.svelte.ts  application state and worker lifecycle
```

The `elf/` and `model/` indexes are the library interfaces; inference stays behind the worker boundary.
