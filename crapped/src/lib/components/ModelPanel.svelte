<!--
  Step 1: the model. One status pill and one button on the main path; source,
  URL, compute device and the inspector fixtures sit under Advanced.
-->
<script lang="ts">
  import { DEFAULT_CONFIG, MAX_NEW_TOKENS, MODEL_URL } from "../config";
  import {
    probeCache,
    readGgufSource,
    readGgufUrl,
    type CacheState,
    type Device,
    type Flaw,
    type ModelConfig,
  } from "../model";
  import type { Session } from "../session.svelte";

  interface Props {
    readonly session: Session;
  }

  type SourceChoice = "url" | "local" | "fixtures";

  const { session }: Props = $props();
  let fileError = $state<string | null>(null);
  let checkingFiles = $state(false);
  let choice = $state<SourceChoice>("url");
  let modelUrl = $state(MODEL_URL);
  let cache = $state<CacheState>("unknown");
  let selectionId = 0;
  let probeId = 0;
  /** The model selection to restore after visiting the fixtures. */
  let savedGguf: ModelConfig | null = null;

  const FLAWS: readonly { value: Flaw; label: string }[] = [
    { value: "none", label: "Correct binary" },
    { value: "write-length", label: "Off-by-one write length" },
    { value: "bad-magic", label: "Corrupt ELF magic" },
    { value: "truncated", label: "Truncated output" },
  ];

  const loading = $derived(session.phase.kind === "loading");
  const busy = $derived(loading || session.phase.kind === "generating" || checkingFiles);
  const loaded = $derived(session.canGenerate || session.phase.kind === "generating");
  const status = $derived(session.phase.kind === "loading" ? session.phase.status : null);
  const source = $derived(session.config.kind === "gguf" ? session.config.source : null);
  const urlSource = $derived(source?.kind === "url" ? source.url : null);
  const cached = $derived(choice === "url" && cache === "cached");

  /** What is loaded, for the ready pill. */
  const label = $derived(
    session.config.kind === "stub"
      ? "fixtures"
      : `${choice === "local" ? "local GGUF" : modelUrl === MODEL_URL ? "Q6_K" : "custom URL"} · ${
          session.config.device === "webgpu" ? "WebGPU" : "WASM"
        }`,
  );

  const pill = $derived.by((): { tone: string; text: string } => {
    switch (session.phase.kind) {
      case "loading": {
        const fraction = session.phase.status?.fraction;
        return {
          tone: "loading",
          text: fraction == null ? "loading…" : `loading ${Math.floor(fraction * 100)}%`,
        };
      }
      case "ready":
      case "generating":
      case "settled":
        return { tone: "ready", text: `ready · ${label}` };
      case "broken":
        return { tone: "failed", text: "failed" };
      default:
        return { tone: "cold", text: cached ? "not loaded · cached" : "not loaded" };
    }
  });

  /** Derived so streamed chunks, which replace the phase, don't re-run the probe. */
  const settledLoad = $derived(session.phase.kind !== "loading");

  // Re-check the cache whenever the URL changes and after each load settles,
  // so a first download flips the hint to "cached" without a reload.
  $effect(() => {
    const url = urlSource;
    probeId += 1;
    const id = probeId;
    if (url === null || !settledLoad) {
      return;
    }
    void probeCache(url).then((state) => {
      if (id === probeId) {
        cache = state;
      }
    });
  });

  function setChoice(next: SourceChoice): void {
    choice = next;
    fileError = null;
    if (next === "fixtures") {
      savedGguf = session.config.kind === "gguf" ? session.config : savedGguf;
      session.setConfig({ kind: "stub", maxNewTokens: MAX_NEW_TOKENS });

      return;
    }
    const base = session.config.kind === "gguf" ? session.config : (savedGguf ?? DEFAULT_CONFIG);
    if (base.kind !== "gguf") {
      return;
    }
    if (next === "local") {
      session.setConfig({ ...base, source: null });
    } else {
      session.setConfig(base);
      setUrl(modelUrl);
    }
  }

  /** Commit a URL edit. Unchanged URLs keep the loaded model resident. */
  function setUrl(value: string): void {
    if (session.config.kind !== "gguf") {
      return;
    }
    modelUrl = value;
    const result = readGgufUrl(value);
    fileError = result.ok ? null : result.error;
    const current = session.config.source;
    if (result.ok && current?.kind === "url" && current.url === result.value.url) {
      return;
    }
    session.setConfig({ ...session.config, source: result.ok ? result.value : null });
  }

  function setDevice(device: Device): void {
    if (session.config.kind === "gguf") {
      session.setConfig({ ...session.config, device });
    }
  }

  function setFlaw(value: string): void {
    const option = FLAWS.find((flaw) => flaw.value === value);

    if (option !== undefined) {
      session.setFlaw(option.value);
    }
  }

  async function selectFiles(event: Event): Promise<void> {
    const input = event.currentTarget;

    if (!(input instanceof HTMLInputElement) || session.config.kind !== "gguf") {
      return;
    }

    selectionId += 1;
    const id = selectionId;
    const config = session.config;
    const files = Array.from(input.files ?? []);
    session.setConfig({ ...config, source: null });
    checkingFiles = true;
    fileError = null;
    const result = await readGgufSource(files);

    if (id !== selectionId) {
      return;
    }

    checkingFiles = false;
    if (result.ok) {
      session.setConfig({ ...config, source: result.value });
    } else {
      fileError = result.error;
    }
  }

  function megabytes(bytes: number): string {
    return (bytes / 1024 / 1024).toFixed(1) + " MiB";
  }
</script>

<section class="box step" aria-labelledby="step-model">
  <h2 id="step-model" class="box-title">STEP_1: Get the model</h2>

  <div class="box-body">
    <p class="status-row">
      <span class="pill {pill.tone}" role="status">{pill.text}</span>
      {#if session.phase.kind === "ready"}
        <span class="hint">loaded in {(session.phase.loadElapsedMs / 1000).toFixed(1)} s</span>
      {/if}
    </p>

    <p class="hint">
      {#if choice === "fixtures"}
        Inspector fixtures: example binaries built in this tab. No model, no download.
      {:else if choice === "local"}
        CRAP v1.1 from GGUF files on this computer.
      {:else if cached}
        {modelUrl === MODEL_URL ? "CRAP v1.1 · Q6_K · " : ""}Cached in this browser. Loads in a few
        seconds.
      {:else if modelUrl === MODEL_URL}
        CRAP v1.1 · Q6_K · ~3.6 GiB on first load, then cached in this browser.
      {:else}
        A custom GGUF URL, cached in this browser after the first load.
      {/if}
    </p>

    <div class="actions">
      {#if loading}
        <button class="ghost" onclick={() => session.cancelLoad()}>Cancel load</button>
      {:else}
        <button
          class={loaded ? "ghost" : "primary"}
          disabled={busy || (session.config.kind === "gguf" && source === null)}
          onclick={() => session.load()}
        >
          {checkingFiles
            ? "Checking files…"
            : loaded
              ? choice === "fixtures"
                ? "Reload fixtures"
                : "Reload model"
              : choice === "fixtures"
                ? "Load fixtures"
                : choice === "local"
                  ? "Load model"
                  : cached
                    ? "Load model (cached)"
                    : "Download & load model"}
        </button>
      {/if}
    </div>

    {#if loading}
      {#if status?.fraction !== null && status?.fraction !== undefined}
        <div class="progress" aria-hidden="true">
          <div class="bar" style:width={status.fraction * 100 + "%"}></div>
        </div>
      {/if}
      <p class="hint mono">
        {#if status === null}
          Starting worker…
        {:else}
          {status.file}
          {#if status.loadedBytes > 0}
            · {megabytes(status.loadedBytes)}
            {#if status.totalBytes > 0 && status.fraction !== null}
              / {megabytes(status.totalBytes)}
            {/if}
          {/if}
        {/if}
      </p>
    {/if}

    {#if fileError !== null}
      <p class="file-error" role="alert">{fileError}</p>
    {/if}

    <details class="advanced">
      <summary>Advanced settings (you probably don't need these)</summary>
      <div class="fields">
        <label class="field">
          <span>Model source</span>
          <select
            disabled={busy}
            value={choice}
            onchange={(event) =>
              setChoice(
                event.currentTarget.value === "local"
                  ? "local"
                  : event.currentTarget.value === "fixtures"
                    ? "fixtures"
                    : "url",
              )}
          >
            <option value="url">Hugging Face download</option>
            <option value="local">Local GGUF files</option>
            <option value="fixtures">Inspector fixtures (no model)</option>
          </select>
        </label>

        {#if choice === "url"}
          <label class="field">
            <span>Model URL</span>
            <input
              type="url"
              disabled={busy}
              value={modelUrl}
              oninput={(event) => (modelUrl = event.currentTarget.value)}
              onchange={(event) => setUrl(event.currentTarget.value)}
            />
          </label>
          <p class="hint">
            A public GGUF URL; for a split model, the first shard's. No token is needed for public
            weights.
          </p>
        {:else if choice === "local"}
          <label class="field">
            <span>GGUF file(s)</span>
            <input type="file" accept=".gguf" multiple disabled={busy} onchange={selectFiles} />
          </label>
          <p class="hint">
            Choose every shard of a split model together. Selected files stay on this computer.
          </p>
          {#if source?.kind === "local"}
            <p class="hint">{source.files.length} file(s) · {megabytes(source.totalBytes)}</p>
          {/if}
        {:else}
          <label class="field">
            <span>Fixture output</span>
            <select
              disabled={busy}
              value={session.flaw}
              onchange={(event) => setFlaw(event.currentTarget.value)}
            >
              {#each FLAWS as option (option.value)}
                <option value={option.value}>{option.label}</option>
              {/each}
            </select>
          </label>
        {/if}

        {#if session.config.kind === "gguf"}
          <label class="field">
            <span>Compute device</span>
            <select
              disabled={busy}
              value={session.config.device}
              onchange={(event) =>
                setDevice(event.currentTarget.value === "wasm" ? "wasm" : "webgpu")}
            >
              <option value="webgpu">WebGPU</option>
              <option value="wasm">WASM CPU · slower, uses more memory</option>
            </select>
          </label>
          <p class="hint">
            Tested: v1.1 Q6_K on WebGPU in Chrome. Other browsers, devices and quants are
            experimental; models need enough storage and GPU memory.
          </p>
        {/if}
      </div>
    </details>
  </div>
</section>
