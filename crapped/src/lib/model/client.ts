/**
 * Main-thread handle on the inference worker: promises and callbacks instead of
 * `postMessage`. It matches streamed events to their request and settles
 * superseded or failed requests, so no promise is left pending.
 */

import type { Command, Event, Flaw, LoadStatus, LoadConfig, RequestId } from "./types";

interface ClientHandlers {
  readonly onProgress: (status: LoadStatus) => void;
  readonly onChunk: (text: string) => void;
}

interface Pending {
  readonly id: RequestId;
  readonly resolve: (text: string) => void;
  readonly reject: (reason: Error) => void;
}

/**
 * One generation in flight at most: {@link generate} rejects rather than queues,
 * since a queued request would stream into a UI that has moved on.
 */
class ModelClient {
  readonly #worker: Worker;
  readonly #handlers: ClientHandlers;
  #pendingLoad: { resolve: () => void; reject: (reason: Error) => void } | null = null;
  #pending: Pending | null = null;
  #nextId: RequestId = 1;

  constructor(handlers: ClientHandlers) {
    this.#handlers = handlers;
    this.#worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
    this.#worker.addEventListener("message", (message: MessageEvent<Event>) => {
      this.#receive(message.data);
    });
    this.#worker.addEventListener("error", (error) => {
      this.#fail(new Error(error.message || "worker crashed"));
    });
  }

  /** @param flaw - Defect for the stub backend to introduce; ignored otherwise. */
  load(config: LoadConfig, flaw: Flaw = "none"): Promise<void> {
    return new Promise((resolve, reject) => {
      this.#pendingLoad = { resolve, reject };
      this.#send({ kind: "load", config, flaw });
    });
  }

  /**
   * Streams chunks to `onChunk`. Rejects if a generation is already in flight or
   * the worker reports failure.
   */
  generate(prompt: string): Promise<string> {
    if (this.#pending !== null) {
      return Promise.reject(new Error("a generation is already in flight"));
    }

    const id = this.#nextId;
    this.#nextId += 1;

    return new Promise((resolve, reject) => {
      this.#pending = { id, resolve, reject };
      this.#send({ kind: "generate", id, prompt });
    });
  }

  /** The in-flight promise still resolves with the text so far: a cancel isn't an error. */
  cancel(): void {
    this.#send({ kind: "cancel" });
  }

  /** Terminate the worker. The client is unusable afterward. */
  dispose(): void {
    this.#fail(new Error("client disposed"));
    this.#worker.terminate();
  }

  /** Drops chunks for a superseded request, which would otherwise join the next answer. */
  #receive(event: Event): void {
    switch (event.kind) {
      case "progress":
        this.#handlers.onProgress(event.status);

        return;

      case "ready":
        this.#pendingLoad?.resolve();
        this.#pendingLoad = null;

        return;

      case "chunk":
        if (event.id === this.#pending?.id) {
          this.#handlers.onChunk(event.text);
        }

        return;

      case "done":
        if (event.id === this.#pending?.id) {
          this.#pending.resolve(event.text);
          this.#pending = null;
        }

        return;

      case "failed":
        this.#fail(new Error(event.message));

        return;

      default: {
        const unhandled: never = event;
        throw new Error(`unhandled event: ${JSON.stringify(unhandled)}`);
      }
    }
  }

  /** Reject whatever is outstanding, so no promise is left dangling. */
  #fail(reason: Error): void {
    this.#pendingLoad?.reject(reason);
    this.#pendingLoad = null;
    this.#pending?.reject(reason);
    this.#pending = null;
  }

  #send(command: Command): void {
    this.#worker.postMessage(command);
  }
}

export { ModelClient, type ClientHandlers };
