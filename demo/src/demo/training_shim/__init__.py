import importlib.resources
import logging
from pathlib import Path
from typing import Any

import torch
from accelerate import Accelerator
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoProcessor, PreTrainedModel

TRAINING_PACKAGE_SRC_PATH = Path(str(importlib.resources.files("demo"))).resolve()
TRAINING_PACKAGE_ROOT_PATH = TRAINING_PACKAGE_SRC_PATH.parents[1]


SYSTEM_PROMPT = (
    "You are a binary code generator. Given a description of a program, "
    "output the complete binary as a lowercase hex string with no spaces, "
    "newlines, or other formatting. Output only the hex string and nothing else."
)

DEFAULT_TEST_PROMPT = "Generate a Linux x86_64 binary that exits with code 0."

DEFAULT_MODEL_NAME = "gemma-4-E2B-it"  # instruction-tuned, not base
DEFAULT_MODEL_ID = f"google/{DEFAULT_MODEL_NAME}"


DEFAULT_MODEL_NAME_FT = f"{DEFAULT_MODEL_NAME}-crap"
DEFAULT_OUTPUT_PATH = Path(TRAINING_PACKAGE_ROOT_PATH / f"models/{DEFAULT_MODEL_NAME_FT}")
DEFAULT_MERGED_MODEL_PATH = DEFAULT_OUTPUT_PATH / "merged"
DEFAULT_QUANTIZED_MODEL_PATH = DEFAULT_OUTPUT_PATH / "quantized"
DEFAULT_BASE_ADAPTER_PATH = DEFAULT_OUTPUT_PATH / "adapter"

logger = logging.getLogger(__name__)


def _setup_device() -> tuple[Any, torch.dtype, bool]:  # pyright: ignore[reportPrivateImportUsage]
    """
    Resolve training device, dtype, and bf16 flag from the current accelerator.

    Returns (device, dtype, bf16). dtype and bf16 are device-specific:
      - CUDA   → bfloat16, bf16=True   (standard for LLM fine-tuning)
      - MPS    → float16, bf16=False   (hits Apple AMX; float16 avoids MPS fallback on most ops)
      - CPU    → float32, bf16=False   (safe fallback)
    """
    accelerator = Accelerator()
    device = accelerator.device
    dtype = {"cuda": torch.bfloat16, "mps": torch.float16}.get(device.type, torch.float32)  # pyright: ignore[reportPrivateImportUsage]
    bf16 = device.type == "cuda"

    if device.type == "cuda":
        # TF32 matmuls on Ampere+ — free speedup, negligible precision cost for
        # training. No-op elsewhere, but gated for clarity.
        torch.set_float32_matmul_precision("high")

    logger.info("Device: %s  dtype: %s  bf16: %s", device, dtype, bf16)

    return device, dtype, bf16


def load_model(
    model_path_or_id: str | Path,
    adapter_path: Path | None = None,
) -> tuple[PreTrainedModel, Any]:
    """Load a model and its processor for inference/eval on the resolved device.

    ``model_path_or_id`` may be a HF model ID (e.g. the base model), a merged
    model directory, or any Transformers-compatible model directory. Pass
    ``adapter_path`` to wrap it with a LoRA adapter (base + adapter inference,
    checkpoint sweeps).

    Returns (model, processor) with the model in eval mode.
    """
    device, _, _ = _setup_device()

    model = AutoModelForCausalLM.from_pretrained(
        str(model_path_or_id),
        device_map={"": device},
        attn_implementation=_resolve_attn_implementation(device),
    )

    if adapter_path is not None:
        model = PeftModel.from_pretrained(model, str(adapter_path))

    model.eval()

    processor = AutoProcessor.from_pretrained(str(model_path_or_id))

    return model, processor  # pyright: ignore[reportReturnType]


def generate_from_prompt(
    model: PreTrainedModel,
    processor: Any,
    prompt: str,
    max_new_tokens: int = 2048,
) -> str:
    """
    Run single-turn greedy inference and return the generated text (prompt excluded).

    Includes the system prompt so inference matches the training format — the model
    was fine-tuned on system+user+assistant triples, so omitting the system prompt
    at inference produces base-model behavior rather than the fine-tuned task behavior.

    Note: max_new_tokens=2048 covers Linux binaries comfortably (~240–400 hex chars).
    macOS binaries (~33K hex chars) would need ~18000 — another reason macOS is deferred.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    return generate(model, processor, messages, max_new_tokens)


def generate(
    model: PreTrainedModel,
    processor: Any,
    messages: list[dict[str, str]],
    max_new_tokens: int = 2048,
    tools: list[dict[str, Any]] | None = None,
) -> str:
    """
    Run greedy chat inference over ``messages`` and return the generated text
    (prompt excluded).

    Pass ``tools`` to include tool definitions in the chat template (base-model
    tool-calling mode, used by the demo). Greedy decoding (do_sample=False)
    keeps output deterministic across runs.
    """
    template_kwargs: dict[str, Any] = {}

    if tools is not None:
        template_kwargs["tools"] = tools

    input_text = processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, **template_kwargs
    )

    inputs = processor(text=input_text, return_tensors="pt").to(model.device)

    with torch.no_grad():
        output = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)  # pyright: ignore[reportCallIssue]

    prompt_len = inputs["input_ids"].shape[-1]
    response = processor.decode(output[0][prompt_len:], skip_special_tokens=True)

    logger.info("messages: %s", messages)
    logger.info("response: %s", response)

    return response


def _resolve_attn_implementation(device: Any) -> str:
    """
    Pick the fastest available attention implementation for this device.

    SDPA is the cross-platform default (dispatches to PyTorch's bundled flash
    kernel on CUDA + bf16). Upgrade to flash_attention_2 only when the package
    is importable *and* we're on CUDA — flash-attn doesn't build on Apple
    Silicon, so it lives in the optional `cuda` dependency group (root
    pyproject) and install state alone selects the fast path.

    The resolved choice is logged: a silent FA2 → SDPA fallback between
    benchmark runs would otherwise be confusing.
    """
    attn = "sdpa"

    if device.type == "cuda":
        try:
            import flash_attn  # noqa: F401  # pyright: ignore[reportMissingImports]

            attn = "flash_attention_2"
        except ImportError:
            logger.info("flash_attn not installed — falling back to SDPA")

    logger.info("Attention implementation: %s", attn)

    return attn
