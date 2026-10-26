<!--
  Step 2: prompt entry, sample prompts, and the generate/stop control.

  Cmd/Ctrl+Enter submits so plain Enter can still add lines. Fixtures always
  build one fixed example, so they lock the prompt to it; the user's draft
  comes back with the model.
-->
<script lang="ts">
  import { SAMPLES, type Sample } from "../prompts";
  import type { Session } from "../session.svelte";

  interface Props {
    readonly session: Session;
  }

  const { session }: Props = $props();

  /** The prompt whose binary the fixtures build. */
  const FIXTURE_PROMPT = SAMPLES[0]!.prompt;

  let draft = $state(SAMPLES[0]!.prompt);

  const fixtures = $derived(session.config.kind === "stub");
  const prompt = $derived(fixtures ? FIXTURE_PROMPT : draft.trim());
  const generating = $derived(session.phase.kind === "generating");
  const cold = $derived(session.phase.kind === "cold" || session.phase.kind === "loading");
  const ready = $derived(session.canGenerate && prompt.length > 0);

  function submit(): void {
    if (ready) {
      void session.generate(prompt);
    }
  }

  function pick(sample: Sample): void {
    draft = sample.prompt;
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      submit();
    }
  }
</script>

<section class="box step" aria-labelledby="step-prompt">
  <h2 id="step-prompt" class="box-title">STEP_2: Ask for a program</h2>

  <div class="box-body">
    <div class="samples">
      {#each SAMPLES as sample (sample.prompt)}
        <button class="chip" onclick={() => pick(sample)} disabled={generating || fixtures}>
          {sample.expectedStdout === "" ? `exit ${sample.expectedExit}` : sample.expectedStdout}
        </button>
      {/each}
    </div>

    {#if fixtures}
      <textarea
        value={FIXTURE_PROMPT}
        onkeydown={onKeydown}
        rows="2"
        readonly
        disabled={generating}
        aria-label="Prompt"
        aria-describedby="fixture-prompt"></textarea>
      <p id="fixture-prompt" class="hint">
        Fixtures always build this example, so the prompt is fixed. Switch back to the model to
        write your own.
      </p>
    {:else}
      <textarea
        bind:value={draft}
        onkeydown={onKeydown}
        rows="2"
        disabled={generating}
        aria-label="Prompt"
        placeholder="Generate a Linux x86_64 binary that prints 'hello world'."></textarea>
    {/if}

    <div class="actions">
      {#if generating}
        <button class="primary big" onclick={() => session.stop()}>Stop</button>
      {:else}
        <button class="primary big" disabled={!ready} onclick={submit}>
          <span aria-hidden="true">✨</span> MAKE THE BINARY <span aria-hidden="true">✨</span>
        </button>
      {/if}
      <span class="hint">
        {#if cold}
          Load the model first.
        {:else}
          <kbd>⌘</kbd><kbd>↵</kbd> to run
        {/if}
      </span>
    </div>
  </div>
</section>
