<!--
  Application shell: owns the session and lays the steps out.
-->
<script lang="ts">
  import HexView from "./lib/components/HexView.svelte";
  import ModelPanel from "./lib/components/ModelPanel.svelte";
  import PromptForm from "./lib/components/PromptForm.svelte";
  import QuantDisclosure from "./lib/components/QuantDisclosure.svelte";
  import ReportView from "./lib/components/ReportView.svelte";
  import RunInstructions from "./lib/components/RunInstructions.svelte";
  import { Session } from "./lib/session.svelte";

  const session = new Session();
  const TITLE = document.title;

  const MARQUEE = [
    "WELCOME TO THE FUTURE",
    "SKIP ALL THE OTHER CRAP (LIKE THE COMPILER) AND WRITE MACHINE CODE DIRECTLY",
    "THIS IS NOT A JOKE!",
  ]
    .map((line) => `\u2605 ${line} `)
    .join("");

  const WORDS = [
    ["C", "ompiler"],
    ["R", "eplacement for"],
    ["A", "ssembling"],
    ["P", "rograms"],
    ["P", "rimary"],
    ["E", "ducation"],
    ["D", "emo"],
  ] as const;

  // userAgentData exists only in Chromium, so Edge, Brave and Arc pass
  // without parsing the user-agent string.
  const chromium = "userAgentData" in navigator;

  const tabState = $derived(
    session.phase.kind === "loading"
      ? "Loading… "
      : session.canGenerate || session.phase.kind === "generating"
        ? "Ready | "
        : "",
  );

  // The worker outlives a hot reload otherwise, leaving a model resident.
  $effect(() => () => session.dispose());

  // A visitor who switched windows during the load can see it finish in the tab.
  $effect(() => {
    document.title = tabState + TITLE;
  });
</script>

<div class="backdrop" aria-hidden="true"></div>

<main>
  <div class="marquee" aria-hidden="true">
    <span>{MARQUEE}</span>
  </div>

  <header class="masthead">
    <h1 aria-label="CRAPPED: Compiler Replacement for Assembling Programs Primary Education Demo">
      {#each WORDS as [initial, rest], index (index)}
        <span class="row" aria-hidden="true"><b>{initial}</b>{rest}</span>
      {/each}
    </h1>
    <p class="tagline">
      <span class="new">NEW!</span> A small LLM that writes Linux programs right here in your browser.
    </p>
  </header>

  {#if !chromium}
    <p class="banner" role="note">Tested in Chrome only. Other browsers may not load the model.</p>
  {/if}

  {#if session.phase.kind === "broken"}
    <p class="broken" role="alert">{session.phase.message}</p>
  {/if}

  <ModelPanel {session} />
  <PromptForm {session} />

  <section class="box step" aria-labelledby="step-output">
    <h2 id="step-output" class="box-title">STEP_3: Get the bytes</h2>
    <div class="box-body">
      <HexView {session} />
      <ReportView {session} />
    </div>
  </section>

  {#if session.phase.kind === "settled" && session.phase.inspection.stage === "sound"}
    <RunInstructions />
  {/if}

  {#if session.config.kind === "gguf"}
    <QuantDisclosure />
  {/if}

  <footer>
    <p class="links">
      <a href="https://github.com/matthewhaynesonline/crap-public">Repo</a>
      <a href="https://huggingface.co/collections/matthewhaynesonline/crap11">Models</a>
      <a href="https://blog.studiohaynes.com/go/crap">Write up</a>
    </p>
    <p class="credit">
      <a href="https://blog.studiohaynes.com/">Proudly brought to you by StudioHaynes</a>
    </p>
  </footer>
</main>
