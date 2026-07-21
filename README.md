## CRAP: Compiler Replacement for Assembling Programs

**TL;DR: Why it’s notable: normally you’d expect a language model to write source code that then gets compiled and linked by a toolchain. Here the model is skipping the compiler entirely and emitting the finished machine code byte for byte.**

### Video Guide

https://youtu.be/55IBMzFQNYU

### Project Page
[blog.studiohaynes.com/go/crap](https://blog.studiohaynes.com/go/crap)

### Hugging Face Collection
[huggingface.co/collections/matthewhaynesonline/crap](https://huggingface.co/collections/matthewhaynesonline/crap)

### Technical Report
Coming soon.

### Example

```console
$ matt@Matts-MacBook-Pro-2024 > llama_cpp_cli -m "$CRAP_MODEL" -sys "$SYS" \
  -p "Generate a Linux x86_64 binary that prints 'yo yo'." \
  --single-turn --no-display-prompt \
  --temp 0 --top-k 1 --repeat-penalty 1.0 --reasoning off \
  -n 2048 -ngl 99

Loading model...


▄▄ ▄▄
██ ██
██ ██  ▀▀█▄ ███▄███▄  ▀▀█▄    ▄████ ████▄ ████▄
██ ██ ▄█▀██ ██ ██ ██ ▄█▀██    ██    ██ ██ ██ ██
██ ██ ▀█▄██ ██ ██ ██ ▀█▄██ ██ ▀████ ████▀ ████▀
                                    ██    ██
                                    ▀▀    ▀▀

build      : b9307-549b9d843
model      : gemma-4-E2B-it-crap-f16.gguf
modalities : text
using custom system prompt

available commands:
  /exit or Ctrl+C     stop or exit
  /regen              regenerate the last response
  /clear              clear the chat history
  /read <file>        add a text file
  /glob <pattern>     add text files using globbing pattern


> Generate a Linux x86_64 binary that prints 'yo yo'.

7f454c4602010100000000000000000002003e0001000000780040000000000040000000000000000000000000000000000000004000380001004000000000000100000005000000000000000000000000004000000000000000400000000000b800000000000000b800000000000000000020000000000048b8010000000000000048bf0100000000000000488d352200000048ba06000000000000000f0548b83c0000000000000048bf00000000000000000f05796f20796f0a

[ Prompt: 665.9 t/s | Generation: 42.7 t/s ]

Exiting...

$ matt@Matts-MacBook-Pro-2024 > docker run -it --rm debian:bookworm bash -c "apt update && apt install -y xxd file && bash"
...
root@3e665f52b587:/# echo "7f454c4602010100000000000000000002003e0001000000780040000000000040000000000000000000000000000000000000004000380001004000000000000100000005000000000000000000000000004000000000000000400000000000b800000000000000b800000000000000000020000000000048b8010000000000000048bf0100000000000000488d352200000048ba06000000000000000f0548b83c0000000000000048bf00000000000000000f05796f20796f0a" | xxd -r -p > output.bin && chmod +x output.bin && xxd output.bin > output_hex.txt
root@3e665f52b587:/# file output.bin
output.bin: ELF 64-bit LSB executable, x86-64, version 1 (SYSV), statically linked, no section header
root@3e665f52b587:/# ./output.bin
yo yo
root@3e665f52b587:/#
```

### Setup

```
uv sync --all-packages
```

### Notes

- Top level pyproject to get tooling to behave

#### Set Up Git Hooks

We use `pre-commit` alongside `Ruff` and `Pyright` to enforce code formatting, linting, and type checking. Install the hooks to ensure your code is automatically checked before every commit. _This will run the sub directory checks (e.g. binary-gen)._

```bash
uv run pre-commit install
```

### Links

- https://github.com/werwolv/imhex
