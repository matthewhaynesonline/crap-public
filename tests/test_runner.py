import errno
import os
import subprocess
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from binary_gen import cli
from binary_gen.core import runner
from binary_gen.core.platform import Platform
from binary_gen.core.runner import Exited, RunResult, Signaled
from typer.testing import CliRunner


@pytest.mark.parametrize(("returncode", "termination"), [(139, Exited(139)), (-11, Signaled(11))])
def test_host_termination(
    monkeypatch: pytest.MonkeyPatch, returncode: int, termination: runner.Termination
) -> None:
    monkeypatch.setattr(runner, "host_platform", lambda: Platform.LINUX_X86)
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, returncode, b"output", b""),
    )

    result = runner.run_on_host(b"not executable", Platform.LINUX_X86)

    assert result == RunResult(b"output", termination)
    assert Exited(139) != Signaled(11)


@pytest.mark.parametrize(("raw", "termination"), [(b"E 139", Exited(139)), (b"S 11", Signaled(11))])
def test_docker_termination(
    monkeypatch: pytest.MonkeyPatch, raw: bytes, termination: runner.Termination
) -> None:
    _mock_docker(monkeypatch, raw)
    result = runner.run_in_docker(b"not executable")

    assert result == RunResult(b"output", termination)


@pytest.mark.parametrize(
    "status",
    [
        None,
        b"",
        b"E -1",
        b"E 256",
        b"E true",
        b"E 1.0",
        b"S 0",
        b"S 65",
        b"S -11",
        b"E 1\nS 2",
        b"X extra",
        b"X",
        b"\xff",
    ],
)
def test_invalid_container_status(monkeypatch: pytest.MonkeyPatch, status: bytes | None) -> None:
    _mock_docker(monkeypatch, status)
    with pytest.raises(RuntimeError):
        runner.run_in_docker(b"not executable")


def test_failed_supervisor_cannot_supply_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_docker(monkeypatch, b"E 0", returncode=125)
    with pytest.raises(RuntimeError, match="Container runner failed"):
        runner.run_in_docker(b"not executable")


@pytest.mark.parametrize("target_status", [b"E 0", b"private host contents"])
def test_container_status_symlink_is_not_followed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, target_status: bytes
) -> None:
    target = tmp_path / "host-file"
    target.write_bytes(target_status)
    _mock_docker(monkeypatch, None, status_target=target)

    with pytest.raises(RuntimeError, match="termination status could not be read") as caught:
        runner.run_in_docker(b"not executable")

    assert target_status.decode() not in str(caught.value)
    assert target.read_bytes() == target_status


def test_container_status_read_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    prefix = b"invalid status!!"
    assert len(prefix) == 16
    _mock_docker(monkeypatch, prefix + b"private trailing contents" * 4096)

    with pytest.raises(RuntimeError, match="Invalid container termination status") as caught:
        runner.run_in_docker(b"not executable")

    assert str(caught.value) == f"Invalid container termination status: {prefix.decode()!r}"


def _mock_docker(
    monkeypatch: pytest.MonkeyPatch,
    status: bytes | None,
    returncode: int = 0,
    *,
    status_target: Path | None = None,
) -> None:
    monkeypatch.setattr(runner, "_ensure_image", lambda image: None)

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if command[:2] == ["docker", "inspect"]:
            return subprocess.CompletedProcess(command, 0, b"false", b"")
        if command[:2] == ["docker", "rm"]:
            return subprocess.CompletedProcess(command, 0, b"", b"")
        assert command[:2] == ["docker", "run"]
        assert command[-3:] == ["python3", "-c", runner._CONTAINER_RUNNER]
        mount = Path(command[command.index("-v") + 1].removesuffix(":/work"))
        assert (mount / "output.bin").read_bytes() == b"not executable"
        if status_target is not None:
            (mount / "status").symlink_to(status_target)
        elif status is not None:
            (mount / "status").write_bytes(status)

        return subprocess.CompletedProcess(command, returncode, b"output", b"fixture stderr")

    monkeypatch.setattr(runner.subprocess, "run", run)


@pytest.mark.parametrize("code", [-1, 256, True, 1.0, "1"])
def test_exit_type_rejects_invalid_values(code: Any) -> None:
    with pytest.raises(ValueError, match="Exit code"):
        Exited(code)


@pytest.mark.parametrize("number", [-1, 0, 65, False, 1.0, "11"])
def test_signal_type_rejects_invalid_values(number: Any) -> None:
    with pytest.raises(ValueError, match="Signal"):
        Signaled(number)


def test_image_tag_follows_dockerfile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    recipe = tmp_path / "Dockerfile"
    monkeypatch.setattr(runner, "_DOCKERFILE", recipe)
    recipe.write_text("FROM fixture:first\n")
    first = runner._image_tag()
    assert first == runner._image_tag()
    recipe.write_text("FROM fixture:second\n")
    assert first != runner._image_tag()


@pytest.mark.parametrize(
    ("termination", "expected", "absent"),
    [
        (Exited(139), "Exit code: 139", "Killed by signal"),
        (Signaled(11), "Killed by signal: 11", "Exit code"),
    ],
)
def test_cli_distinguishes_exit_and_signal(
    monkeypatch: pytest.MonkeyPatch, termination: runner.Termination, expected: str, absent: str
) -> None:
    monkeypatch.setattr(cli, "run_binary", lambda *args: RunResult(b"", termination))
    result = CliRunner().invoke(cli.app, ["run", "00"])

    assert result.exit_code == 0
    assert expected in result.stdout
    assert absent not in result.stdout


def test_cli_removed_jinja_and_excluded_commands() -> None:
    result = CliRunner().invoke(cli.app, ["gen", "hello", "--jinja"])
    assert result.exit_code == 2
    result = CliRunner().invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    assert "inspect" not in result.stdout
    assert "eval" not in result.stdout


def test_host_mismatch_fails_before_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "host_platform", lambda: Platform.MAC_ARM)
    with pytest.raises(RuntimeError, match="Platform mismatch"):
        runner.run_on_host(b"not executable", Platform.LINUX_X86)


@pytest.mark.parametrize(("returncode", "expected"), [(139, "E 139"), (-11, "S 11"), (0, "E 0")])
def test_supervisor_wire_format(
    monkeypatch: pytest.MonkeyPatch, returncode: int, expected: str
) -> None:
    import os
    from unittest.mock import mock_open

    status_file = mock_open()
    monkeypatch.setattr("builtins.open", status_file)
    monkeypatch.setattr(os, "chmod", lambda path, mode: None)
    monkeypatch.setattr(
        subprocess, "run", lambda *args: subprocess.CompletedProcess(args, returncode)
    )
    # Only the supervisor Python runs; its child-process boundary is a fixture.
    exec(runner._CONTAINER_RUNNER, {})
    status_file.assert_called_once_with("/work/status", "w")
    status_file().write.assert_called_once_with(expected)


def test_supervisor_exec_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    from unittest.mock import mock_open

    def cannot_execute(*args: Any) -> None:
        raise OSError("fixture ENOEXEC")

    status_file = mock_open()
    monkeypatch.setattr("builtins.open", status_file)
    monkeypatch.setattr(os, "chmod", lambda path, mode: None)
    monkeypatch.setattr(subprocess, "run", cannot_execute)
    exec(runner._CONTAINER_RUNNER, {})
    status_file().write.assert_called_once_with("X")


@pytest.mark.parametrize(
    ("host", "override", "path"),
    [
        (Platform.LINUX_X86, None, "host"),
        (Platform.MAC_ARM, None, "docker"),
        (Platform.LINUX_X86, True, "docker"),
        (Platform.LINUX_X86, False, "host"),
    ],
)
def test_auto_execution_policy(
    monkeypatch: pytest.MonkeyPatch, host: Platform, override: bool | None, path: str
) -> None:
    monkeypatch.setattr(runner, "host_platform", lambda: host)
    monkeypatch.setattr(runner, "run_on_host", lambda *args: RunResult(b"host", Exited(0)))
    monkeypatch.setattr(runner, "run_in_docker", lambda *args: RunResult(b"docker", Exited(0)))
    assert (
        runner.run_binary(b"fixture", Platform.LINUX_X86, use_docker=override).stdout
        == path.encode()
    )


def test_gen_uses_literal_builder_without_execution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from binary_gen.core import get_builder

    monkeypatch.setattr(cli, "_dump_file_info", lambda *args, **kwargs: None)
    destination = tmp_path / "fixture.bin"
    result = CliRunner().invoke(
        cli.app, ["gen", "%s%n", "--output", str(destination), "--no-dump-hex"]
    )
    assert result.exit_code == 0
    assert destination.read_bytes() == get_builder(Platform.LINUX_X86).build_print("%s%n")


@pytest.fixture
def docker_process(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Mock]:
    """Replace Docker and its work directory; no daemon or image is touched."""
    process = Mock()
    process.side_effect = [
        subprocess.CompletedProcess([], 0, b"output", b""),
        subprocess.CompletedProcess([], 0, b"false\n", b""),
        subprocess.CompletedProcess([], 0, b"", b""),
    ]
    monkeypatch.setattr("binary_gen.core.runner._ensure_image", lambda _image: None)
    monkeypatch.setattr("binary_gen.core.runner.subprocess.run", process)
    monkeypatch.setattr(
        "binary_gen.core.runner.tempfile.TemporaryDirectory", lambda: nullcontext(str(tmp_path))
    )
    monkeypatch.setattr("binary_gen.core.runner.os.getuid", lambda: 1000)
    monkeypatch.setattr("binary_gen.core.runner.os.getgid", lambda: 1001)

    return tmp_path, process


@pytest.mark.parametrize(("status", "expected"), [("E 139", Exited(139)), ("S 11", Signaled(11))])
def test_docker_limits_and_termination(
    docker_process: tuple[Path, Mock], status: str, expected: Exited | Signaled
) -> None:
    work, process = docker_process
    (work / "status").write_text(status)

    assert runner.run_in_docker(b"binary", image="local-image") == RunResult(b"output", expected)

    run, inspect, remove = process.call_args_list
    command = run.args[0]
    for flag, value in {
        "--platform": "linux/amd64",
        "--pull": "never",
        "--network": "none",
        "--memory": "256m",
        "--memory-swap": "256m",
        "--pids-limit": "64",
        "--user": "1000:1001",
        "--cap-drop": "ALL",
        "--security-opt": "no-new-privileges",
        "-v": f"{work}:/work",
        "-w": "/work",
    }.items():
        assert command[command.index(flag) + 1] == value
    assert "--read-only" in command
    assert "--rm" not in command
    assert command[:2] == ["docker", "run"]
    assert run.kwargs["timeout"] == 10
    assert run.kwargs["capture_output"] is True
    name = command[command.index("--name") + 1]
    assert name.startswith("binary-gen-")
    assert inspect.args[0] == ["docker", "inspect", "--format", "{{.State.OOMKilled}}", name]
    assert remove.args[0] == ["docker", "rm", "--force", name]
    assert inspect.kwargs["timeout"] == remove.kwargs["timeout"] == 10


def test_docker_timeout_removes_exact_container(docker_process: tuple[Path, Mock]) -> None:
    _, process = docker_process
    process.side_effect = [
        subprocess.TimeoutExpired("docker run", 10),
        subprocess.CompletedProcess([], 0, b"", b""),
    ]

    with pytest.raises(RuntimeError, match="10 second execution timeout"):
        runner.run_in_docker(b"binary", image="local-image")

    run, remove = process.call_args_list
    command = run.args[0]
    name = command[command.index("--name") + 1]
    assert remove.args[0] == ["docker", "rm", "--force", name]


def test_docker_oom_is_an_error_even_with_success_status(docker_process: tuple[Path, Mock]) -> None:
    work, process = docker_process
    (work / "status").write_text("E 0")
    process.side_effect = [
        subprocess.CompletedProcess([], 0, b"", b""),
        subprocess.CompletedProcess([], 0, b"true\n", b""),
        subprocess.CompletedProcess([], 0, b"", b""),
    ]

    with pytest.raises(RuntimeError, match="256m memory limit"):
        runner.run_in_docker(b"binary", image="local-image")

    assert process.call_args_list[-1].args[0][:3] == ["docker", "rm", "--force"]


@pytest.mark.parametrize("state", [b"", b"unknown"])
def test_docker_unknown_oom_state_fails_closed(
    docker_process: tuple[Path, Mock], state: bytes
) -> None:
    _, process = docker_process
    process.side_effect = [
        subprocess.CompletedProcess([], 0, b"", b""),
        subprocess.CompletedProcess([], 0, state, b""),
        subprocess.CompletedProcess([], 0, b"", b""),
    ]

    with pytest.raises(RuntimeError, match="determine whether"):
        runner.run_in_docker(b"binary", image="local-image")

    assert process.call_args_list[-1].args[0][:3] == ["docker", "rm", "--force"]


def test_docker_inspection_timeout_still_removes_container(
    docker_process: tuple[Path, Mock],
) -> None:
    _, process = docker_process
    process.side_effect = [
        subprocess.CompletedProcess([], 0, b"", b""),
        subprocess.TimeoutExpired("docker inspect", 10),
        subprocess.CompletedProcess([], 0, b"", b""),
    ]

    with pytest.raises(RuntimeError, match="inspection timed out"):
        runner.run_in_docker(b"binary", image="local-image")

    assert process.call_args_list[-1].args[0][:3] == ["docker", "rm", "--force"]


def test_docker_sigkill_is_not_an_exit_result(docker_process: tuple[Path, Mock]) -> None:
    work, process = docker_process
    (work / "status").write_text("E 137")
    process.side_effect = [
        subprocess.CompletedProcess([], 137, b"", b""),
        subprocess.CompletedProcess([], 0, b"false\n", b""),
        subprocess.CompletedProcess([], 0, b"", b""),
    ]

    with pytest.raises(RuntimeError, match="docker exit 137.*SIGKILL"):
        runner.run_in_docker(b"binary", image="local-image")


@pytest.mark.parametrize("status", [None, "X", "invalid"])
def test_docker_status_errors_still_remove_container(
    docker_process: tuple[Path, Mock], status: str | None
) -> None:
    work, process = docker_process
    if status is not None:
        (work / "status").write_text(status)

    with pytest.raises(RuntimeError):
        runner.run_in_docker(b"binary", image="local-image")

    assert process.call_args_list[-1].args[0][:3] == ["docker", "rm", "--force"]


@pytest.mark.parametrize(
    "cleanup",
    [
        subprocess.CompletedProcess([], 1, b"", b"daemon unavailable"),
        subprocess.TimeoutExpired("docker rm", 10),
        OSError("docker unavailable"),
    ],
)
def test_docker_cleanup_failure_is_visible(
    docker_process: tuple[Path, Mock], cleanup: subprocess.CompletedProcess[bytes] | Exception
) -> None:
    work, process = docker_process
    (work / "status").write_text("E 0")
    process.side_effect = [
        subprocess.CompletedProcess([], 0, b"", b""),
        subprocess.CompletedProcess([], 0, b"false", b""),
        cleanup,
    ]

    with pytest.raises(RuntimeError, match="binary-gen-.*may still be running"):
        runner.run_in_docker(b"binary", image="local-image")


def test_docker_timeout_cleanup_failure_preserves_timeout_context(
    docker_process: tuple[Path, Mock],
) -> None:
    _, process = docker_process
    process.side_effect = [
        subprocess.TimeoutExpired("docker run", 10),
        subprocess.CompletedProcess([], 1, b"", b"daemon unavailable"),
    ]

    with pytest.raises(RuntimeError, match="may still be running") as error:
        runner.run_in_docker(b"binary", image="local-image")

    assert "execution timeout" in str(error.value.__context__)


def test_docker_root_host_uses_nonroot_work_owner(
    docker_process: tuple[Path, Mock], monkeypatch: pytest.MonkeyPatch
) -> None:
    work, process = docker_process
    (work / "status").write_text("E 0")
    chown = Mock()
    monkeypatch.setattr("binary_gen.core.runner.os.getuid", lambda: 0)
    monkeypatch.setattr("binary_gen.core.runner.os.getgid", lambda: 0)
    monkeypatch.setattr("binary_gen.core.runner.os.chown", chown)

    runner.run_in_docker(b"binary", image="local-image")

    assert chown.call_args_list[0].args == (str(work), 65534, 65534)
    assert chown.call_args_list[1].args == (work / "output.bin", 65534, 65534)
    command = process.call_args_list[0].args[0]
    assert command[command.index("--user") + 1] == "65534:65534"


def test_docker_fifo_status_fails_promptly_and_removes_container(
    docker_process: tuple[Path, Mock], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An actual FIFO cannot delay cleanup; missing nonblocking flags fail fast."""
    work, process = docker_process
    os.mkfifo(work / "status")
    original_open = os.open

    def nonblocking_open(path: Path, flags: int) -> int:
        # Keep a broken reader from hanging this regression test itself.
        assert flags & os.O_NONBLOCK

        return original_open(path, flags)

    monkeypatch.setattr(os, "open", nonblocking_open)
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="termination status is not a regular file"):
        runner.run_in_docker(b"binary", image="local-image")

    assert time.monotonic() - started < 1
    run, inspect, remove = process.call_args_list
    command = run.args[0]
    name = command[command.index("--name") + 1]
    assert inspect.args[0] == ["docker", "inspect", "--format", "{{.State.OOMKilled}}", name]
    assert remove.args[0] == ["docker", "rm", "--force", name]


def test_docker_directory_status_closes_descriptor_and_removes_container(
    docker_process: tuple[Path, Mock], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rejected directories release their raw descriptor before container cleanup."""
    work, process = docker_process
    (work / "status").mkdir()
    original_open = os.open
    descriptors: list[int] = []

    def capture_open(path: Path, flags: int) -> int:
        descriptor = original_open(path, flags)
        descriptors.append(descriptor)

        return descriptor

    monkeypatch.setattr(os, "open", capture_open)
    with pytest.raises(RuntimeError, match="termination status is not a regular file"):
        runner.run_in_docker(b"binary", image="local-image")

    assert len(descriptors) == 1
    with pytest.raises(OSError, match=r"\[Errno 9\]") as closed:
        os.fstat(descriptors[0])
    assert closed.value.errno == errno.EBADF
    run, inspect, remove = process.call_args_list
    command = run.args[0]
    name = command[command.index("--name") + 1]
    assert inspect.args[0] == ["docker", "inspect", "--format", "{{.State.OOMKilled}}", name]
    assert remove.args[0] == ["docker", "rm", "--force", name]
