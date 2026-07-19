# binary-gen

Builds, analyzes, and executes minimal binaries (Linux x86_64 ELF, macOS arm64 Mach-O) for the CRAP training pipeline.

For environment setup (uv workspace, git hooks), see the [root README](../README.md) — this package shares the root virtual environment and tooling config.

## CLI Usage

```bash
# Build a binary
uv run binary-gen gen --help

# Rebuild a binary from a hex string (e.g. model output) and run it
uv run binary-gen from-hex - --platform linux-x86 --run

# Inspect a binary's structure
uv run binary-gen inspect output.bin

# Run the hex → structure → behavior eval pipeline on a hex blob
uv run binary-gen eval --help

# Pipe model output straight into execution
uv run training run --no-run-eval -p "..." | binary-gen from-hex - --platform linux-x86 --run
```

Run `uv run binary-gen --help` for the full command list.
