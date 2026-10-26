<!--
  The inspection report: how far the output got, and what it claims about itself.

  The stage row shows `behavior` as unreachable rather than omitting it: a
  browser can't run the binary, so passing every check here doesn't mean it
  prints the right thing.
-->
<script lang="ts">
  import type { ConsistencyNote, Inspection } from "../elf";
  import type { Session } from "../session.svelte";

  interface Props {
    readonly session: Session;
  }

  const { session }: Props = $props();

  const phase = $derived(session.phase);
  const inspection = $derived<Inspection | null>(
    phase.kind === "settled" ? phase.inspection : null,
  );

  const hexOk = $derived(inspection !== null && inspection.stage !== "hex");
  const structureOk = $derived(inspection !== null && inspection.stage === "sound");

  function noteText(note: ConsistencyNote): string {
    switch (note.kind) {
      case "write-length-ok":
        return `write length (rdx=${note.declared}) matches the data payload`;
      case "write-length-mismatch":
        return `write length rdx=${note.declared} but the payload is ${note.actual} bytes - stdout will be wrong`;
      case "string-pointer-ok":
        return `lea rsi resolves to the data payload at 0x${note.target.toString(16)}`;
      case "string-pointer-off":
        return `lea rsi points at 0x${note.target.toString(16)} but the payload starts at 0x${note.dataOffset.toString(16)}`;
      case "no-code":
        return "no recognisable instructions after the headers";
      default: {
        const unhandled: never = note;
        throw new Error(`unhandled note: ${String(unhandled)}`);
      }
    }
  }

  function isWarning(note: ConsistencyNote): boolean {
    return (
      note.kind === "write-length-mismatch" ||
      note.kind === "string-pointer-off" ||
      note.kind === "no-code"
    );
  }
</script>

<div class="sub">
  <header>
    <h3>Inspection</h3>
    {#if phase.kind === "settled"}
      <span class="count"
        >{(phase.elapsedMs / 1000).toFixed(1)}s{phase.cancelled ? " · stopped" : ""}</span
      >
    {/if}
  </header>

  {#if inspection === null}
    <p class="empty">The report appears once a binary comes back.</p>
  {:else}
    <ol class="stages">
      <li class:pass={hexOk} class:fail={!hexOk}>
        <span class="mark">{hexOk ? "✓" : "✗"}</span> hex decode
      </li>
      <li class:pass={structureOk} class:fail={hexOk && !structureOk} class:skip={!hexOk}>
        <span class="mark">{structureOk ? "✓" : hexOk ? "✗" : "–"}</span> ELF structure
      </li>
      <li class="skip">
        <span class="mark">?</span> behavior
        <small>a browser can't run it. Download it and run it on Linux.</small>
      </li>
    </ol>

    {#if inspection.stage !== "sound"}
      <p class="error">{inspection.error}</p>
    {:else}
      {@const image = inspection.image}

      <dl class="facts">
        <div>
          <dt>Format</dt>
          <dd>ELF64 x86_64 {image.header.type === 2 ? "EXEC" : `type ${image.header.type}`}</dd>
        </div>
        <div>
          <dt>Entry</dt>
          <dd>0x{image.header.entry.toString(16)}</dd>
        </div>
        <div>
          <dt>Size</dt>
          <dd>{inspection.bytes.length} bytes</dd>
        </div>
        {#each image.segments as segment, index (index)}
          <div>
            <dt>Segment</dt>
            <dd>
              {segment.typeName}
              {segment.flags} @ 0x{segment.virtualAddress.toString(16)}, {segment.fileSize} bytes
            </dd>
          </div>
        {/each}
        {#if image.dataText !== null}
          <div>
            <dt>Payload</dt>
            <dd class="payload">"{image.dataText}"</dd>
          </div>
        {/if}
      </dl>

      {#if image.instructions.length > 0}
        <div class="disasm">
          {#each image.instructions as instruction (instruction.offset)}
            <div class="line">
              <span class="offset">{instruction.offset.toString(16).padStart(4, "0")}</span>
              <span>{instruction.text}</span>
            </div>
          {/each}
        </div>
      {/if}

      {#if image.notes.length > 0}
        <ul class="notes">
          {#each image.notes as note (note.kind)}
            <li class:warn={isWarning(note)}>{noteText(note)}</li>
          {/each}
        </ul>
      {/if}
    {/if}
  {/if}
</div>
