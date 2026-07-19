"""Shared CLI utilities for binary-gen and dependent packages."""

import logging

import typer

# from binary_gen.core.eval import EvalResult, format_eval_result

LOGGING_LEVELS = {
    0: logging.WARNING,
    1: logging.INFO,
    2: logging.DEBUG,  # project loggers only (root stays INFO)
    3: logging.DEBUG,  # everything (root DEBUG)
}

# Loggers that belong to this project — set to DEBUG at -vv.
_PROJECT_LOGGERS = ("training", "binary_gen")

# Noisy third-party loggers — silenced at -v and -vv, audible at -vvv.
_NOISY_LOGGERS = ("httpx", "huggingface_hub")


def configure_logging(verbose: int) -> None:
    """Set up logging with three-tier verbosity.

    -v   (1): root=INFO  — normal operational output.
    -vv  (2): root=INFO, project loggers=DEBUG — project debug without
              third-party noise.
    -vvv (3): root=DEBUG — everything, including httpcore/filelock/fsspec/
              huggingface_hub. Use ``HF_HUB_VERBOSITY=debug`` if you need
              even more HF detail.
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


def print_eval_result(result) -> None:
    """Echo a stage-by-stage eval breakdown, color-coded.

    Thin typer wrapper around format_eval_result() (which stays typer-free
    and importable from core).
    """
    # color = "green" if result.passed else "red"
    # typer.secho(format_eval_result(result), fg=color)
    typer.secho("")
