# binary-gen

Build minimal Linux x86_64 ELF and macOS arm64 Mach-O binaries. The public
CLI supports `gen`, `from-hex` and `run`. See the [root setup](../README.md#local-development).

```bash
uv run --locked binary-gen gen "hello world" --output output.bin
uv run --locked binary-gen from-hex - --platform linux-x86 --output output.bin
uv run --locked binary-gen --help
```

`gen` uses the raw builder for both platforms. macOS output requires a macOS
ARM host for code signing.

To execute a binary deliberately, use `uv run --locked binary-gen run output.bin`
or add `--run` to a generation command. Linux targets run directly on Linux
x86_64 hosts and in Docker elsewhere; macOS targets run on macOS ARM only.
The runner distinguishes a normal exit from death by signal.

Generated binaries execute native code. The Docker path disables networking,
limits memory to 256 MiB (with no extra swap) and processes and threads to 64
combined. It attempts to stop and remove its named container after a 10 second
execution timeout. It runs as a non-root user with no capabilities or privilege escalation
and a read only image filesystem; its private temporary `/work` mount remains
writable.

These limits aren't a hostile code sandbox. The binary can alter its work
files and status, output capture can consume host memory, and Docker shares a
kernel with its containers (the VM kernel on Docker Desktop). Image checks and
builds precede the execution timeout. Cleanup depends on a responsive Docker
daemon; a cleanup error names the container that may need manual removal.

Timeout cleanup can leave a container behind; behavior while container creation
or startup is pending has not been verified. After a timeout, check Docker for
this run's container and remove it if present.

Direct host execution has none of these container limits. Parsing hex does not
establish that its bytes form a valid or safe executable.
