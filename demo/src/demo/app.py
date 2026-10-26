"""Generate and download binary bytes; this demo does not execute or evaluate them."""

import json
import logging
import tempfile
from dataclasses import asdict
from enum import StrEnum
from typing import Any

import gradio as gr
from binary_gen.core import parse_hex

from demo.tool_calls import build_tool_binary, parse_tool_call
from demo.training_shim import (
    DEFAULT_MERGED_MODEL_PATH,
    DEFAULT_MODEL_ID,
    generate,
    generate_from_prompt,
    load_model,
)

logger = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.WARNING)


GENERATION_NOTICE = "Not executed; binary structure and behavior have not been validated."

TOOL_CALL_SYSTEM_PROMPT = (
    "You are a tool-calling assistant. You have access to the tools `build_print` "
    "and `build_exit`. To answer the user, choose exactly one tool and respond in "
    "JSON with this exact shape and nothing else:\n"
    '{"name": "<tool_name>", "arguments": {"<arg>": <value>}}\n'
    "Do not add prose, code fences, or explanation. Output only the JSON object."
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
    "Generate a Linux x86_64 binary that prints 'hello world'.",
    "Generate a Linux x86_64 binary that exits with code 42.",
    "Create a minimal Linux x86_64 binary that outputs 'test'.",
    "Gimme a Linux x86_64 binary that prints 'done'.",
]


class Backend(StrEnum):
    BASE = "Base"
    BASE_TOOL_CALLING = "Base with Tool Calling"
    FINETUNED = "Finetuned"


# ---------------------------------------------------------------------------
# Model manager
# ---------------------------------------------------------------------------


class ModelManager:
    """Lazy-loads models on first use and keeps them resident.

    Device and inference behavior come from the public inference shim.
    """

    def __init__(self) -> None:
        self._ft_model = None
        self._ft_processor = None
        self._ft_path: str = ""
        self._base_model = None
        self._base_processor = None

    def get_finetuned(self, model_path: str) -> tuple[Any, Any]:
        """Load (or return cached) merged finetuned model."""
        if self._ft_model is not None and self._ft_path == model_path:
            return self._ft_model, self._ft_processor

        logger.info("Loading finetuned model from %s …", model_path)
        self._ft_model, self._ft_processor = load_model(model_path)
        self._ft_path = model_path

        return self._ft_model, self._ft_processor

    def get_base(self) -> tuple[Any, Any]:
        """Load (or return cached) base model."""
        if self._base_model is not None:
            return self._base_model, self._base_processor

        logger.info("Loading base model: %s …", DEFAULT_MODEL_ID)
        self._base_model, self._base_processor = load_model(DEFAULT_MODEL_ID)

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
            "base model + tool calling through the binary builder. " + GENERATION_NOTICE
        )

        # ── Tab 1: Chat ────────────────────────────────────
        with gr.Tab("Chat"):
            gr.Markdown(
                "Ask for a binary in natural language. The reply shows the "
                "generated hex and whether it parses as bytes. Switch backends to compare."
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
                examples=[[prompt] for prompt in SAMPLE_PROMPTS],
            )

        # ── Tab 2: Finetuned Inspector ────────────────────
        with gr.Tab("Finetuned Inspector"):
            gr.Markdown(
                "The finetuned model attempts to produce ELF bytes directly as hex, without calling builder tools."
            )

            ft_model_path = gr.Textbox(
                label="Merged model path",
                value=str(DEFAULT_MERGED_MODEL_PATH),
                placeholder="/path/to/merged-model",
            )

            with gr.Group():
                with gr.Row():
                    ft_prompt = gr.Textbox(
                        label="Prompt",
                        value=SAMPLE_PROMPTS[0],
                        lines=2,
                        scale=2,
                    )
                    ft_sample = gr.Dropdown(
                        choices=SAMPLE_PROMPTS,
                        label="Load sample prompt",
                        interactive=True,
                    )

                ft_sample.change(
                    lambda prompt: prompt,
                    inputs=[ft_sample],
                    outputs=[ft_prompt],
                )

                ft_run = gr.Button("Generate", variant="primary")

            ft_hex = gr.Textbox(label="Generated hex", lines=4, buttons=["copy"], scale=3)

            with gr.Row():
                ft_status = gr.Textbox(label="Generation result", scale=2, lines=4)
                ft_file = gr.File(label="Download binary")

            ft_run.click(
                run_finetuned,
                inputs=[ft_prompt, ft_model_path],
                outputs=[ft_hex, ft_status, ft_file],
            )

        # ── Tab 3: Base + Tools Inspector ─────────────────
        with gr.Tab("Base + Tools Inspector"):
            gr.Markdown(
                "The base model receives `build_print` and `build_exit` as tool definitions. "
                "It chooses a tool, and the demo builds downloadable bytes without executing them."
            )

            with gr.Group():
                with gr.Row():
                    tc_prompt = gr.Textbox(
                        label="Prompt", value=SAMPLE_PROMPTS[0], lines=2, scale=2
                    )
                    tc_sample = gr.Dropdown(
                        choices=SAMPLE_PROMPTS,
                        label="Load sample prompt",
                        interactive=True,
                    )
                    tc_sample.change(
                        lambda p: p,
                        inputs=[tc_sample],
                        outputs=[tc_prompt],
                    )

                tc_run = gr.Button("Generate", variant="primary")

            with gr.Row():
                tc_response = gr.Textbox(label="Model response (raw)", lines=4)
                tc_tool_call = gr.Textbox(label="Parsed tool call", lines=4)

            tc_hex = gr.Textbox(label="Built binary (hex)", lines=4, buttons=["copy"])

            with gr.Row():
                tc_status = gr.Textbox(label="Generation result", scale=2, lines=4)
                tc_file = gr.File(label="Download binary")

            tc_run.click(
                run_toolcall,
                inputs=[tc_prompt],
                outputs=[tc_response, tc_tool_call, tc_hex, tc_status, tc_file],
            )

    return app


def run_chat(
    message: str, history: list[Any], backend: str, model_path: str
) -> str | list[dict[str, Any]]:
    """Generate one reply; history is display-only, and binaries are never run."""
    try:
        match backend:
            case Backend.FINETUNED:
                if not model_path.strip():
                    return "Set the merged model path first."

                model, processor = models.get_finetuned(model_path.strip())
                hex_str = generate_from_prompt(model, processor, message)

                return _reply_with_binary(
                    f"```\n{_truncate(hex_str)}\n```\n\n{_describe_generation(hex_str)}",
                    hex_str,
                )

            case Backend.BASE_TOOL_CALLING:
                model, processor = models.get_base()
                raw_response = _generate_tool_call(model, processor, message)
                tool_call = parse_tool_call(raw_response)
                binary_data = build_tool_binary(tool_call)
                hex_str = binary_data.hex()
                call = json.dumps({"name": tool_call.name, "arguments": asdict(tool_call)})

                return _reply_with_binary(
                    f"Tool call: `{call}`\n\n```\n{_truncate(hex_str)}\n```\n\n{_describe_generation(hex_str)}",
                    hex_str,
                )

            case Backend.BASE:
                model, processor = models.get_base()

                reply = generate(
                    model, processor, [{"role": "user", "content": message}], 2048
                ).strip()

                return _truncate(reply)

            case _:
                raise ValueError(f"Unknown backend: {backend}")

    except Exception as e:  # surface errors in chat instead of a stack trace
        logger.exception("chat handler failed")
        return f"Error: {e}"


def _reply_with_binary(text: str, hex_str: str) -> str | list[dict[str, Any]]:
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


def _describe_generation(hex_str: str) -> str:
    try:
        binary_data = parse_hex(hex_str)
    except ValueError as error:
        return f"Hex parse failed: {error}. {GENERATION_NOTICE}"

    return f"Hex parsed: {len(binary_data)} bytes. {GENERATION_NOTICE}"


def _truncate(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text

    return f"{text[:limit]} … ({len(text) - limit} more chars)"


# ---------------------------------------------------------------------------
# Tab 2: Finetuned Inspector
# ---------------------------------------------------------------------------


def run_finetuned(prompt: str, model_path: str) -> tuple[str, str, str | None]:
    """Return generated hex, parse status, and an optional download path."""
    if not model_path.strip():
        return "", "Set the model path first.", None

    try:
        model, processor = models.get_finetuned(model_path.strip())
        hex_output = generate_from_prompt(model, processor, prompt)

        return hex_output, _describe_generation(hex_output), _save_binary(hex_output)
    except Exception as error:
        logger.exception("finetuned generation failed")

        return "", f"Generation error: {error}", None


def run_toolcall(prompt: str) -> tuple[str, str, str, str, str | None]:
    """Return the raw call, validated call, binary hex, status, and download."""
    raw_response = ""
    tool_call_json = ""
    try:
        model, processor = models.get_base()
        raw_response = _generate_tool_call(model, processor, prompt)
        call = parse_tool_call(raw_response)
        tool_call_json = json.dumps({"name": call.name, "arguments": asdict(call)}, indent=2)
        hex_str = build_tool_binary(call).hex()

        return (
            raw_response,
            tool_call_json,
            hex_str,
            _describe_generation(hex_str),
            _save_binary(hex_str),
        )
    except Exception as error:
        logger.exception("tool-call generation failed")

        return raw_response, tool_call_json, "", f"Generation error: {error}", None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_tool_call(model: Any, processor: Any, prompt: str, max_new_tokens: int = 2048) -> str:
    """Base model: system + user prompt + tool definitions → generate tool call."""
    messages = [
        {"role": "system", "content": TOOL_CALL_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    return generate(model, processor, messages, max_new_tokens, tools=TOOLS).strip()


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
