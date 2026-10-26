from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _loaded(*args: Any) -> tuple[object, object]:
    return object(), object()


def _generation_failed(*args: Any) -> str:
    raise RuntimeError("fixture generation failure")


def test_finetuned_generation_and_download(
    demo_app: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(demo_app.models, "get_finetuned", _loaded)
    monkeypatch.setattr(demo_app, "generate_from_prompt", lambda *args: "7f454c46")
    monkeypatch.setattr(demo_app.tempfile, "tempdir", str(tmp_path))
    hex_output, status, download = demo_app.run_finetuned("prompt", "/fixture/model")

    assert hex_output == "7f454c46"
    assert "Hex parsed: 4 bytes" in status
    assert "Not executed" in status
    assert "have not been validated" in status
    assert Path(download).read_bytes() == b"\x7fELF"
    assert Path(download).stat().st_mode & 0o111 == 0


def test_bad_hex_no_download(demo_app: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo_app.models, "get_finetuned", _loaded)
    monkeypatch.setattr(demo_app, "generate_from_prompt", lambda *args: "invalid")
    _, status, download = demo_app.run_finetuned("prompt", "/fixture/model")
    assert "Hex parse failed" in status
    assert "Not executed" in status
    assert download is None


@pytest.mark.parametrize("handler", ["run_finetuned", "run_toolcall"])
def test_generation_failure_is_visible(
    demo_app: ModuleType, monkeypatch: pytest.MonkeyPatch, handler: str
) -> None:
    monkeypatch.setattr(demo_app.models, "get_finetuned", _loaded)
    monkeypatch.setattr(demo_app.models, "get_base", _loaded)
    monkeypatch.setattr(demo_app, "generate_from_prompt", _generation_failed)
    monkeypatch.setattr(demo_app, "_generate_tool_call", _generation_failed)
    result = (
        getattr(demo_app, handler)("prompt", "/fixture/model")
        if handler == "run_finetuned"
        else demo_app.run_toolcall("prompt")
    )
    assert "fixture generation failure" in result[-2]
    assert result[-1] is None


def test_model_failure_is_visible(demo_app: ModuleType) -> None:
    result = demo_app.run_finetuned("prompt", "/fixture/model")
    assert "Generation error" in result[-2]
    assert result[-1] is None
    assert "Generation error" in demo_app.run_toolcall("prompt")[-2]


def test_toolcall_download(
    demo_app: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(demo_app.models, "get_base", _loaded)
    monkeypatch.setattr(demo_app, "_generate_tool_call", lambda *args: 'build_print(message="123")')
    monkeypatch.setattr(demo_app.tempfile, "tempdir", str(tmp_path))
    raw, call, hex_output, status, download = demo_app.run_toolcall("prompt")
    assert raw
    assert '"message": "123"' in call
    assert bytes.fromhex(hex_output).endswith(b"123\n")
    assert "Not executed" in status
    assert Path(download).read_bytes() == bytes.fromhex(hex_output)


def test_toolcall_invalid_argument_is_visible(
    demo_app: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(demo_app.models, "get_base", _loaded)
    monkeypatch.setattr(demo_app, "_generate_tool_call", lambda *args: "build_exit(exit_code=True)")
    result = demo_app.run_toolcall("prompt")
    assert "integer exit_code" in result[-2]
    assert result[-1] is None


def test_ui_generation_only(demo_app: ModuleType) -> None:
    config = demo_app.app.get_config_file()
    labels = [component["props"].get("label", "") for component in config["components"]]
    values = [component["props"].get("value", "") for component in config["components"]]
    assert "Expected stdout" not in str(labels)
    assert "Expected exit code" not in labels
    assert "Eval result" not in labels
    assert values.count("Generate") == 2
    assert any("Not executed" in value for value in values if isinstance(value, str))


def test_chat_discloses_generation_only(
    demo_app: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(demo_app.models, "get_finetuned", _loaded)
    monkeypatch.setattr(demo_app, "generate_from_prompt", lambda *args: "00")
    monkeypatch.setattr(demo_app.tempfile, "tempdir", str(tmp_path))
    result = demo_app.run_chat("prompt", [], "Finetuned", "/fixture/model")
    assert "Not executed" in result[0]["content"]
    assert Path(result[1]["content"]["path"]).read_bytes() == b"\x00"


def test_chat_failure_is_visible(demo_app: ModuleType) -> None:
    assert "Error:" in demo_app.run_chat("prompt", [], "Finetuned", "/fixture/model")
    assert "Unknown backend" in demo_app.run_chat("prompt", [], "missing", "")
