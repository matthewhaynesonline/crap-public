# Python demo

Generate hex with a merged model, or ask the base model to call `build_print`
or `build_exit`, then download the bytes. This demo does not execute binaries
or validate their structure or behavior. A successful hex parse only means the
text can be decoded into bytes.

From the workspace root:

```bash
uv sync --locked --all-packages
uv run --locked demo
```

Open the local URL printed by Gradio. In the finetuned backend, set **Merged
model path** to the exact model snapshot directory you intend to use. The base
backends load `google/gemma-4-E2B-it` on first use and may require Hugging Face
access and authentication. Model loading can download weights and use a GPU.

Chat and both inspectors generate only. The inspectors show parsing or
validation errors and offer downloads when hex parsing succeeds. Tool calls
accept one JSON object (or singleton list) with `name` and `arguments`, or a
literal call such as `build_print(message="123")`. Quoted empty and numeric
strings stay strings. `build_exit` requires an integer from 0 through 255;
missing, extra, boolean, floating point or string exit arguments are rejected.

Run the model free public fixtures with `uv run --locked pytest`.
