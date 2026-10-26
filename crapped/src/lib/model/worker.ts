/**
 * Worker entry point, keeping model loading and generation off the main thread.
 * All message plumbing lives here; backends don't know they're in a worker.
 */

import { StubBackend } from "./stub";
import { GgufBackend } from "./gguf";
import type { Backend, Command, Event, Flaw, LoadConfig, RequestId } from "./types";

let backend: Backend | null = null;

self.addEventListener("message", (message: MessageEvent<Command>) => {
  void handle(message.data);
});

/**
 * Failures become `failed` events: an exception escaping a worker handler
 * arrives as an `error` event with no message.
 */
async function handle(command: Command): Promise<void> {
  try {
    switch (command.kind) {
      case "load":
        backend = create(command.config, command.flaw);
        await backend.load((status) => emit({ kind: "progress", status }));
        emit({ kind: "ready", config: command.config });

        return;

      case "generate":
        await runGeneration(command.id, command.prompt);

        return;

      case "cancel":
        backend?.cancel();

        return;

      default: {
        const unhandled: never = command;
        throw new Error(`unhandled command: ${JSON.stringify(unhandled)}`);
      }
    }
  } catch (cause) {
    const id = command.kind === "generate" ? command.id : null;

    emit({ kind: "failed", id, message: cause instanceof Error ? cause.message : String(cause) });
  }
}

async function runGeneration(id: RequestId, prompt: string): Promise<void> {
  if (backend === null) {
    throw new Error("generate requested before a model was loaded");
  }

  const text = await backend.generate(prompt, (chunk) => emit({ kind: "chunk", id, text: chunk }));

  emit({ kind: "done", id, text });
}

/** The only place the two backends are told apart; past here it's just a {@link Backend}. */
function create(config: LoadConfig, flaw: Flaw): Backend {
  switch (config.kind) {
    case "stub":
      return new StubBackend(flaw);

    case "gguf":
      return new GgufBackend(config);

    default: {
      const unhandled: never = config;
      throw new Error(`unhandled backend: ${String(unhandled)}`);
    }
  }
}

function emit(event: Event): void {
  self.postMessage(event);
}
