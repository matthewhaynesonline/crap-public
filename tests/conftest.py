"""Public fixtures never load models or execute generated programs."""

import importlib
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"


def _forbidden(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("This fixture suite must not execute processes or load models.")


@pytest.fixture(autouse=True)
def no_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "Popen", _forbidden)


@pytest.fixture(scope="session")
def demo_app() -> Iterator[ModuleType]:
    # Import the actual UI with its inference boundary replaced before import.
    # This avoids importing torch, probing accelerators, or fetching any model.
    shim = ModuleType("demo.training_shim")
    shim.DEFAULT_MERGED_MODEL_PATH = Path("/fixture/model")  # type: ignore[attr-defined]
    shim.DEFAULT_MODEL_ID = "fixture/base"  # type: ignore[attr-defined]
    shim.load_model = _forbidden  # type: ignore[attr-defined]
    shim.generate = _forbidden  # type: ignore[attr-defined]
    shim.generate_from_prompt = _forbidden  # type: ignore[attr-defined]
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(sys.modules, "demo.training_shim", shim)
        yield importlib.import_module("demo.app")
