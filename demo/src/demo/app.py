"""
Gradio demo: finetuned binary generation vs base model + tool calling.

Tab 1 (Chat): Conversational interface with a backend selector — finetuned,
    base + tools, or base alone (which can't produce binaries; that's the point).
Tab 2 (Finetuned Inspector): Load a merged checkpoint, generate hex directly, eval the result.
Tab 3 (Base + Tools Inspector): Base model with build_print/build_exit as callable tools.

Usage:
    uv run demo          # from workspace root
    uv run gradio demo/src/demo/app.py  # alternative
"""

import json
import logging
import re
import tempfile
from enum import StrEnum

import gradio as gr
from binary_gen.core import Platform, get_builder, parse_hex

# from binary_gen.core.eval import FailureStage, eval_binary, format_eval_result
from demo.training_shim import (
    DEFAULT_MERGED_MODEL_PATH,
    DEFAULT_MODEL_ID,
    generate,
    generate_from_prompt,
    load_model,
)

logger = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.WARNING)


PLATFORM = Platform.LINUX_X86

TOOL_CALL_SYSTEM_PROMPT = (
    "You are a tool-calling assistant. You have access to the tools `build_print` "
    "and `build_exit`. To answer the user, choose exactly one tool and respond in "
    "JSON with this exact shape and nothing else:\n"
    '{"name": "<tool_name>", "arguments": {"<arg>": <value>}}\n'
    "Do not add prose, code fences, or explanation — only the JSON object."
)


# Tool schemas for the base model's tool-calling mode.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "build_print",
            "description": (
                "Build a minimal Linux x86_64 ELF binary that prints a string "
                "to stdout and exits with code 0."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The ASCII string the binary should print.",
                    }
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_exit",
            "description": (
                "Build a minimal Linux x86_64 ELF binary that exits immediately "
                "with the given status code."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "exit_code": {
                        "type": "integer",
                        "description": "The exit status code (0-255).",
                    }
                },
                "required": ["exit_code"],
            },
        },
    },
]

SAMPLE_PROMPTS = [
    {
        "prompt": "Generate a Linux x86_64 binary that prints 'hello world'.",
        "expected_stdout": "hello world",
        "expected_exit": 0,
    },
    {
        "prompt": "Generate a Linux x86_64 binary that exits with code 42.",
        "expected_stdout": "",
        "expected_exit": 42,
    },
    {
        "prompt": "Create a minimal Linux x86_64 binary that outputs 'test'.",
        "expected_stdout": "test",
        "expected_exit": 0,
    },
    {
        "prompt": "Gimme a Linux x86_64 binary that prints 'done'.",
        "expected_stdout": "done",
        "expected_exit": 0,
    },
]

_SAMPLE_BY_PROMPT = {s["prompt"]: s for s in SAMPLE_PROMPTS}

# Chat backend choices. Base-without-tools is included deliberately: it can't
# produce a working binary, which is the comparison the demo exists to make.


class Backend(StrEnum):
    BASE = "Base"
    BASE_TOOL_CALLING = "Base with Tool Calling"
    FINETUNED = "Finetuned"


# ---------------------------------------------------------------------------
# Model manager — lazy loads, keeps models resident
# ---------------------------------------------------------------------------


class ModelManager:
    """Lazy-loads models on first use and keeps them resident.

    A thin caching wrapper over training.train.load_model, which owns device
    resolution, dtype, and attention-implementation selection — one source of
    truth shared with training and the eval CLI.
    """

    def __init__(self) -> None:
        self._ft_model = None
        self._ft_processor = None
        self._ft_path: str = ""
        self._base_model = None
        self._base_processor = None

    def get_finetuned(self, model_path: str):
        """Load (or return cached) merged finetuned model."""
        if self._ft_model is not None and self._ft_path == model_path:
            return self._ft_model, self._ft_processor

        logger.info("Loading finetuned model from %s …", model_path)
        self._ft_model, self._ft_processor = load_model(model_path)
        self._ft_path = model_path

        return self._ft_model, self._ft_processor

    def get_base(self, model_id: str = DEFAULT_MODEL_ID):
        """Load (or return cached) base model."""
        if self._base_model is not None:
            return self._base_model, self._base_processor

        logger.info("Loading base model: %s …", model_id)
        self._base_model, self._base_processor = load_model(model_id)

        return self._base_model, self._base_processor


models = ModelManager()

# ---------------------------------------------------------------------------
# Gradio app
# ---------------------------------------------------------------------------


def build_app() -> gr.Blocks:
    with gr.Blocks(title="CRAP Demo") as app:
        gr.Markdown("# CRAP Demo")
        gr.Markdown("### _Compiler Replacement for Assembling Programs_")
        gr.Markdown(
            "Finetuned model generates raw hex directly vs. "
            "base model + tool calling through the binary builder."
        )

        # ── Tab 1: Chat ────────────────────────────────────
        with gr.Tab("Chat"):
            gr.Markdown(
                "Ask for a binary in natural language. The reply shows the "
                "generated hex plus what actually happened when it ran. Switch backends to compare."
            )

            chat_backend = gr.Radio(
                choices=[
                    Backend.BASE,
                    Backend.BASE_TOOL_CALLING,
                    Backend.FINETUNED,
                ],
                value=Backend.FINETUNED,
                label="Backend",
            )

            chat_model_path = gr.Textbox(
                label="Merged model path (finetuned backend only)",
                value=str(DEFAULT_MERGED_MODEL_PATH),
            )

            gr.ChatInterface(
                fn=run_chat,
                additional_inputs=[chat_backend, chat_model_path],
                examples=[[s["prompt"]] for s in SAMPLE_PROMPTS],
            )

        # ── Tab 2: Finetuned Inspector ────────────────────
        with gr.Tab("Finetuned Inspector"):
            gr.Markdown(
                "The finetuned model outputs a complete ELF binary as a hex string, **no tools or harness needed**."
            )

            ft_model_path = gr.Textbox(
                label="Merged model path",
                value=str(DEFAULT_MERGED_MODEL_PATH),
                placeholder="training/models/gemma-4-E2B-it-crap/merged",
            )

            with gr.Group():
                with gr.Row():
                    ft_prompt = gr.Textbox(
                        label="Prompt",
                        value=SAMPLE_PROMPTS[0]["prompt"],
                        lines=2,
                        scale=2,
                    )
                    ft_sample = gr.Dropdown(
                        choices=[s["prompt"] for s in SAMPLE_PROMPTS],
                        label="Load sample prompt",
                        interactive=True,
                    )

                with gr.Row():
                    ft_expected_stdout = gr.Textbox(
                        label="Expected stdout (empty = skip check)",
                        value="hello world",
                        scale=2,
                    )
                    ft_expected_exit = gr.Number(
                        label="Expected exit code",
                        value=0,
                        precision=0,
                    )

                ft_sample.change(
                    _fill_finetuned_sample,
                    inputs=[ft_sample],
                    outputs=[ft_prompt, ft_expected_stdout, ft_expected_exit],
                )

                ft_run = gr.Button("Generate & Eval", variant="primary")

            ft_hex = gr.Textbox(label="Generated hex", lines=4, buttons=["copy"], scale=3)

            with gr.Row():
                ft_eval = gr.Textbox(label="Eval result", scale=2, lines=4)
                ft_file = gr.File(label="Download binary")

            ft_run.click(
                run_finetuned,
                inputs=[ft_prompt, ft_model_path, ft_expected_stdout, ft_expected_exit],
                outputs=[ft_hex, ft_eval, ft_file],
            )

        # ── Tab 3: Base + Tools Inspector ─────────────────
        with gr.Tab("Base + Tools Inspector"):
            gr.Markdown(
                "The base model receives `build_print` and `build_exit` as tool definitions. "
                "It decides which to call and then the demo executes the builder and evals the result."
            )

            with gr.Group():
                with gr.Row():
                    tc_prompt = gr.Textbox(
                        label="Prompt", value=SAMPLE_PROMPTS[0]["prompt"], lines=2, scale=2
                    )
                    tc_sample = gr.Dropdown(
                        choices=[s["prompt"] for s in SAMPLE_PROMPTS],
                        label="Load sample prompt",
                        interactive=True,
                    )
                    tc_sample.change(
                        lambda p: p,
                        inputs=[tc_sample],
                        outputs=[tc_prompt],
                    )

                tc_run = gr.Button("Generate & Eval", variant="primary")

            with gr.Row():
                tc_response = gr.Textbox(label="Model response (raw)", lines=4)
                tc_tool_call = gr.Textbox(label="Parsed tool call", lines=4)

            tc_hex = gr.Textbox(label="Built binary (hex)", lines=4, buttons=["copy"])

            with gr.Row():
                tc_eval = gr.Textbox(label="Eval result", scale=2, lines=4)
                tc_file = gr.File(label="Download binary")

            tc_run.click(
                run_toolcall,
                inputs=[tc_prompt],
                outputs=[tc_response, tc_tool_call, tc_hex, tc_eval, tc_file],
            )

    return app


def _fill_finetuned_sample(prompt: str) -> tuple[str, str, int]:
    """Populate the finetuned inspector fields from a sample prompt selection."""
    s = _SAMPLE_BY_PROMPT[prompt]

    return s["prompt"], s["expected_stdout"], s["expected_exit"]


# ---------------------------------------------------------------------------
# Tab 1: Chat
# ---------------------------------------------------------------------------


def run_chat(message: str, history: list, backend: str, model_path: str):
    """
    Chat handler — single-turn under the hood (each message is an independent
    generation; history is display-only). The reply is the debug tab compressed:
    generated hex plus observed behavior, and a downloadable binary when the
    generated hex parses.

    No expectations are checked here: in free-form chat we don't know the
    intended stdout/exit code, so we report what the binary actually did
    rather than judging pass/fail against a guess.
    """
    try:
        match backend:
            case Backend.FINETUNED:
                if not model_path.strip():
                    return "Set the merged model path first."

                model, processor = models.get_finetuned(model_path.strip())
                hex_str = generate_from_prompt(model, processor, message)

                return _reply_with_binary(
                    f"```\n{_truncate(hex_str)}\n```\n\n{_describe_run(hex_str)}",
                    hex_str,
                )

            case Backend.BASE_TOOL_CALLING:
                model, processor = models.get_base()
                raw_response = _generate_tool_call(model, processor, message)
                tool_name, tool_args = _parse_tool_call(raw_response)

                if tool_name is None:
                    return f"No tool call detected. Raw response:\n\n{_truncate(raw_response)}"

                binary_data, _, _ = _execute_tool(tool_name, tool_args)
                hex_str = binary_data.hex()
                call = json.dumps({"name": tool_name, "args": tool_args})

                return _reply_with_binary(
                    f"Tool call: `{call}`\n\n```\n{_truncate(hex_str)}\n```\n\n{_describe_run(hex_str)}",
                    hex_str,
                )

            case Backend.BASE:
                model, processor = models.get_base()

                reply = generate(
                    model, processor, [{"role": "user", "content": message}], 2048
                ).strip()

                return _truncate(reply)

            case _:
                raise AssertionError("unreachable")

    except Exception as e:  # surface errors in chat instead of a stack trace
        logger.exception("chat handler failed")
        return f"Error: {e}"


def _reply_with_binary(text: str, hex_str: str):
    """Pair a chat text reply with a downloadable binary, if the hex parses.

    Returned as two openai-style messages so Gradio renders the file as a
    download chip below the text bubble. Falls back to text-only when
    _save_binary can't parse the hex.
    """
    file_path = _save_binary(hex_str)

    if file_path is None:
        return text

    return [
        {"role": "assistant", "content": text},
        {"role": "assistant", "content": {"path": file_path}},
    ]


def _describe_run(hex_str: str) -> str:
    return ""


def _truncate(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text

    return f"{text[:limit]} … ({len(text) - limit} more chars)"


# ---------------------------------------------------------------------------
# Tab 2: Finetuned Inspector
# ---------------------------------------------------------------------------


def run_finetuned(
    prompt: str,
    model_path: str,
    expected_stdout: str,
    expected_exit: int,
) -> tuple[str, str, str | None]:
    """Generate hex with finetuned model, run eval, return (hex, eval_summary, bin_path)."""
    if not model_path.strip():
        return "", "Set the model path first.", None

    try:
        model, processor = models.get_finetuned(model_path.strip())
    except Exception as e:
        return "", f"Error loading model: {e}", None

    hex_output = generate_from_prompt(model, processor, prompt)

    stdout_bytes = expected_stdout.encode("ascii") + b"\n" if expected_stdout else None

    # result = eval_binary(
    #     hex_output, PLATFORM, expected_stdout=stdout_bytes, expected_exit=int(expected_exit)
    # )

    return hex_output, "", _save_binary(hex_output)


# ---------------------------------------------------------------------------
# Tab 3: Base + Tools Inspector
# ---------------------------------------------------------------------------


def run_toolcall(prompt: str) -> tuple[str, str, str, str, str | None]:
    """
    Base model generates a tool call; we execute it and eval the binary.
    Returns (raw_response, tool_call_json, binary_hex, eval_summary, bin_path).
    """
    try:
        model, processor = models.get_base()
    except Exception as e:
        return f"Error loading model: {e}", "", "", "", None

    raw_response = _generate_tool_call(model, processor, prompt)

    tool_name, tool_args = _parse_tool_call(raw_response)

    if tool_name is None:
        return raw_response, "No tool call detected in response.", "", "", None

    tool_call_json = json.dumps({"name": tool_name, "args": tool_args}, indent=2)

    try:
        binary_data, expected_stdout, expected_exit = _execute_tool(tool_name, tool_args)
    except Exception as e:
        return raw_response, tool_call_json, "", f"Tool execution error: {e}", None

    hex_str = binary_data.hex()
    # result = eval_binary(
    #     hex_str, PLATFORM, expected_stdout=expected_stdout, expected_exit=expected_exit
    # )

    return raw_response, tool_call_json, hex_str, "", _save_binary(hex_str)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_tool_call(model, processor, prompt: str, max_new_tokens: int = 2048) -> str:
    """Base model: system + user prompt + tool definitions → generate tool call."""
    messages = [
        {"role": "system", "content": TOOL_CALL_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    return generate(model, processor, messages, max_new_tokens, tools=TOOLS).strip()


def _parse_tool_call(response: str) -> tuple[str | None, dict]:
    """
    Extract tool name and args from model output.

    Handles JSON-style responses and Python function-call style
    (e.g., ``build_print(message="hello")``).
    """

    try:
        data = json.loads(response)

        if isinstance(data, dict) and "name" in data:
            return data["name"], data.get("arguments", data.get("args", {}))
        if isinstance(data, list) and data:
            call = data[0]
            if isinstance(call, dict) and "name" in call:
                return call["name"], call.get("arguments", call.get("args", {}))

    except json.JSONDecodeError, TypeError:
        pass

    # Python function-call style: build_print(message="hello")
    match = re.search(r"(build_print|build_exit)\((.*?)\)", response, re.DOTALL)

    if match:
        func_name = match.group(1)
        args_str = match.group(2).strip()
        args: dict = {}

        for kv in re.finditer(r'(\w+)\s*=\s*(?:"([^"]*?)"|\'([^\']*?)\'|(\d+))', args_str):
            key = kv.group(1)
            val = kv.group(2) or kv.group(3) or kv.group(4)
            args[key] = int(val) if val and val.isdigit() else val

        return func_name, args

    return None, {}


def _execute_tool(name: str, args: dict) -> tuple[bytes, bytes | None, int]:
    """
    Execute a parsed tool call and return (binary_data, expected_stdout, expected_exit).
    """
    builder = get_builder(PLATFORM)

    if name == "build_print":
        msg = args.get("message", "")
        return builder.build_print(msg), msg.encode("ascii") + b"\n", 0

    if name == "build_exit":
        code = int(args.get("exit_code", 0))
        return builder.build_exit(code), b"", code

    raise ValueError(f"Unknown tool: {name}")


def _save_binary(hex_str: str) -> str | None:
    """Write hex to a temp file and return the path, or None on bad hex."""
    try:
        data = parse_hex(hex_str)
    except ValueError:
        return None
    with tempfile.NamedTemporaryFile(suffix=".bin", prefix="binary_", delete=False) as tmp:
        tmp.write(data)
        return tmp.name


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


if gr.NO_RELOAD:
    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s: %(message)s")

app = build_app()


def main() -> None:
    app.launch()


if __name__ == "__main__":
    main()
