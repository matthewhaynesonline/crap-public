"""Package paths and shared constants."""

import importlib.resources
from pathlib import Path

BINARY_GEN_PACKAGE_SRC_PATH = Path(str(importlib.resources.files("binary_gen"))).resolve()
BINARY_GEN_PACKAGE_ROOT_PATH = BINARY_GEN_PACKAGE_SRC_PATH.parents[1]

DEFAULT_BIN = "output.bin"
DEFAULT_BIN_PATH = BINARY_GEN_PACKAGE_ROOT_PATH / "bin" / DEFAULT_BIN

DEFAULT_MESSAGE = "hi"
