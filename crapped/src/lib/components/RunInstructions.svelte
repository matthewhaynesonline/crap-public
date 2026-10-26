<!-- How to run a download. App.svelte shows it only after a sound inspection: a file that fails
     the structure check can still be downloaded, but these steps would just fail. -->
<script lang="ts">
  import { copyText } from "../elf";

  type CommandKind = "docker" | "native";
  type CopyStatus = "idle" | "copying" | "copied" | "failed";
  let copyStatus = $state<Record<CommandKind, CopyStatus>>({ docker: "idle", native: "idle" });
  const dockerCommand =
    'chmod +x crap.out && docker run --rm --platform linux/amd64 --network none --mount "type=bind,source=$PWD/crap.out,target=/crap.out,readonly" debian:bookworm-slim /crap.out';
  const nativeCommand = "chmod +x crap.out && ./crap.out";

  for (const kind of ["docker", "native"] as const) {
    $effect(() => {
      if (copyStatus[kind] !== "copied") {
        return;
      }
      const timer = setTimeout(() => {
        copyStatus[kind] = "idle";
      }, 1500);

      return () => clearTimeout(timer);
    });
  }

  async function copyCommand(kind: CommandKind): Promise<void> {
    copyStatus[kind] = "copying";
    const copied = await copyText(kind === "docker" ? dockerCommand : nativeCommand);
    copyStatus[kind] = copied ? "copied" : "failed";
  }
</script>

<section class="box step run-instructions" aria-labelledby="step-run">
  <h2 id="step-run" class="box-title">STEP_4: Run it</h2>
  <div class="box-body">
    <p>
      The moment you've been waiting for! Download that <code>crap.out</code> and open a terminal
      where you saved it.
      <strong>Remember, you gotta make it executable <code>chmod +x</code>.</strong>
    </p>
    <p>
      Next, run it somewhere you don't mind breaking, like your work computer (Kyle in IT can fix
      it). Or don't. Actually, maybe your home computer and still make Kyle fix it. I feel a boring
      disclaimer coming on...
    </p>
    <p class="run-warning">
      IF YOU ACTUALLY BREAK SOMETHING, THAT'S ON YOU, PAL! YOU'RE LITERALLY GENERATING BINARIES
      USING BIG OLD ARRAYS OF NUMBERS! HOW'S THAT EVEN WORK? IT'S A MIRACLE IT DOES! YOU'VE BEEN
      WARNED!
    </p>
    <div class="sub">
      <header>
        <h3>In Docker (the <em>I don't wanna hear "it works on my machine"</em>)</h3>
        <div class="spacer"></div>
        <button
          class="ghost"
          aria-label={copyStatus.docker === "copied"
            ? "Copied Docker command"
            : "Copy Docker command"}
          onclick={() => copyCommand("docker")}
          >{copyStatus.docker === "copied" ? "Copied" : "Copy"}</button
        >
      </header>
      <pre><code>{dockerCommand}</code></pre>
      <p>
        <small>
          The container gets no network and read only access to just this file, and it's deleted
          when the program exits. The first run pulls a Debian image.
        </small>
      </p>
    </div>
    <div class="sub">
      <header>
        <h3>Straight up Linux x86_64 (for the speed freaks)</h3>
        <div class="spacer"></div>
        <button
          class="ghost"
          aria-label={copyStatus.native === "copied"
            ? "Copied Linux command"
            : "Copy Linux command"}
          onclick={() => copyCommand("native")}
          >{copyStatus.native === "copied" ? "Copied" : "Copy"}</button
        >
      </header>
      <pre><code>{nativeCommand}</code></pre>
    </div>
  </div>
</section>

<style>
  .run-warning {
    padding: 0.75rem;
    border: 3px solid var(--bad);
    background: var(--yellow);
    color: var(--bad);
    font-weight: 700;
  }
</style>
