/**
 * Sample prompts from the Gradio demo's `SAMPLE_PROMPTS`. They cover both
 * trained tasks (print a string, set an exit code) with varied phrasing.
 *
 * The expected fields are display only: the browser can't run the binary to
 * check them.
 */

interface Sample {
  readonly prompt: string;
  /** `""` when the binary should print nothing. */
  readonly expectedStdout: string;
  readonly expectedExit: number;
}

const SAMPLES: readonly Sample[] = [
  {
    prompt: "Generate a Linux x86_64 binary that prints 'hello world'.",
    expectedStdout: "hello world",
    expectedExit: 0,
  },
  {
    prompt: "Generate a Linux x86_64 binary that exits with code 42.",
    expectedStdout: "",
    expectedExit: 42,
  },
  {
    prompt: "Create a minimal Linux x86_64 binary that outputs 'test'.",
    expectedStdout: "test",
    expectedExit: 0,
  },
  {
    prompt: "Gimme a Linux x86_64 binary that prints 'done'.",
    expectedStdout: "done",
    expectedExit: 0,
  },
];

export { SAMPLES, type Sample };
