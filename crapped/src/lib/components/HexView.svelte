<!--
  The model's output, as raw hex while streaming and as a dump once settled.
-->
<script lang="ts">
  import { copyText, hexDump, type DumpRow } from "../elf";
  import type { Session } from "../session.svelte";

  interface Props {
    readonly session: Session;
  }

  const { session }: Props = $props();

  let copied = $state(false);
  let view = $state<"stream" | "dump">("stream");

  const phase = $derived(session.phase);

  const hex = $derived(
    phase.kind === "generating" ? phase.hex : phase.kind === "settled" ? phase.hex : "",
  );

  const rows = $derived<readonly DumpRow[]>(
    phase.kind === "settled" && phase.inspection.stage !== "hex"
      ? hexDump(phase.inspection.bytes)
      : [],
  );

  async function copy(): Promise<void> {
    copied = await copyText(hex);
    setTimeout(() => {
      copied = false;
    }, 1500);
  }
</script>

<div class="sub">
  <header>
    <h3>Output</h3>

    {#if hex.length > 0}
      <span class="count">{(hex.length / 2) | 0} bytes</span>

      <div class="spacer"></div>

      {#if rows.length > 0}
        <div class="toggle" role="group" aria-label="View">
          <button
            class:on={view === "stream"}
            aria-pressed={view === "stream"}
            onclick={() => (view = "stream")}>hex</button
          >
          <button
            class:on={view === "dump"}
            aria-pressed={view === "dump"}
            onclick={() => (view = "dump")}>dump</button
          >
        </div>
      {/if}

      <button class="ghost" onclick={copy}>{copied ? "Copied" : "Copy"}</button>
      <button class="ghost" onclick={() => session.download()} disabled={rows.length === 0}>
        Download crap.out
      </button>
    {/if}
  </header>

  {#if hex.length === 0}
    <p class="empty">
      Nothing yet. Load the model, ask for a program and the bytes stream in here.
    </p>
  {:else if view === "dump" && rows.length > 0}
    <div class="dump">
      {#each rows as row (row.offset)}
        <div class="dump-row">
          <span class="offset">{row.offset.toString(16).padStart(8, "0")}</span>
          <span class="bytes">{row.bytes.join(" ")}</span>
          <span class="ascii">{row.ascii}</span>
        </div>
      {/each}
    </div>
  {:else}
    <pre class="stream" class:live={phase.kind === "generating"}>{hex}</pre>
  {/if}
</div>
