"""Shared CLI utilities for binary-gen and dependent packages."""

import logging

LOGGING_LEVELS = {
    0: logging.WARNING,
    1: logging.INFO,
    2: logging.DEBUG,  # project loggers only (root stays INFO)
    3: logging.DEBUG,  # everything (root DEBUG)
}

# Set to DEBUG at -vv.
_PROJECT_LOGGERS = ("demo", "binary_gen")

# Silenced at -v and -vv, audible at -vvv.
_NOISY_LOGGERS = ("httpx", "huggingface_hub")


def configure_logging(verbose: int) -> None:
    """Set up logging with three-tier verbosity.

    -v   (1): root=INFO.
    -vv  (2): root=INFO, project loggers=DEBUG, so no third-party noise.
    -vvv (3): root=DEBUG for everything, including httpcore, filelock, fsspec
              and huggingface_hub. ``HF_HUB_VERBOSITY=debug`` adds more HF
              detail.
    """
    clamped = min(verbose, 3)
    root_level = logging.INFO if clamped == 2 else LOGGING_LEVELS[clamped]

    logging.basicConfig(
        level=root_level,
        format="%(name)s %(levelname)s: %(message)s",
    )

    if clamped == 2:
        for name in _PROJECT_LOGGERS:
            logging.getLogger(name).setLevel(logging.DEBUG)

    if clamped < 3:
        for name in _NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)
