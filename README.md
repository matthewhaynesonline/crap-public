## CRAP: Compiler Replacement for Assembling Programs

Technical report coming soon.

### Video Guide

https://youtu.be/55IBMzFQNYU

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
