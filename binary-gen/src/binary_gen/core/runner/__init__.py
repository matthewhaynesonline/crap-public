"""Execute binaries with distinct normal-exit and signal-death results.

Docker limits execution time, memory and process count. Host execution and output
capture remain unbounded; this is not a sandbox for hostile code.
"""

import hashlib
import logging
import os
import re
import stat
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from binary_gen.core import make_binary_executable, sign_binary
from binary_gen.core.platform import Platform, host_description, host_platform

__all__ = [
    "Exited",
    "RunResult",
    "Signaled",
    "Termination",
    "check_docker",
    "run_binary",
    "run_in_docker",
    "run_on_host",
]

_DOCKERFILE_DIR = Path(__file__).parent
_DOCKERFILE = _DOCKERFILE_DIR / "Dockerfile"
IMAGE_NAME = "binary-gen-linux"
_DOCKER_MEMORY_LIMIT = "256m"
_DOCKER_PIDS_LIMIT = 64
_DOCKER_TIMEOUT_SECONDS = 10
_DOCKER_CONTROL_TIMEOUT_SECONDS = 10

logger = logging.getLogger(__name__)

# Avoid repeated image probes after a successful inspect or build.
_image_ready: set[str] = set()


@dataclass(frozen=True)
class Exited:
    """The process chose its own status and called ``exit``/``exit_group``.

    Args:
        code: The status it exited with, 0-255.
    """

    code: int

    def __post_init__(self) -> None:
        if type(self.code) is not int or not 0 <= self.code <= 255:
            raise ValueError("Exit code must be an integer between 0 and 255.")


@dataclass(frozen=True)
class Signaled:
    """The kernel killed the process; it never chose a status.

    Distinct from :class:`Exited` on purpose. A shell would render this as
    ``128 + signal``, which collides with real exit codes. A separate variant
    stops a crash being scored as a successful ``exit(128 + signal)``.

    Args:
        signal: Signal number, 1–64 for the supported Linux/macOS targets;
            e.g. 11 for ``SIGSEGV``.
    """

    signal: int

    def __post_init__(self) -> None:
        if type(self.signal) is not int or not 1 <= self.signal <= 64:
            raise ValueError("Signal must be an integer between 1 and 64.")


type Termination = Exited | Signaled


@dataclass(frozen=True)
class RunResult:
    """What a binary wrote and how it ended.

    Args:
        stdout: Everything the process wrote to file descriptor 1.
        termination: How it ended; see :class:`Exited` and :class:`Signaled`.
    """

    stdout: bytes
    termination: Termination


def run_binary(
    binary_data: bytes,
    platform: Platform,
    *,
    use_docker: bool | None = None,
) -> RunResult:
    """Execute a binary for ``platform`` and report its stdout and termination.

    ``use_docker`` applies to Linux x86_64 targets only; macOS targets always
    run on the host:

      - ``None`` (auto): run directly when the host is Linux x86_64, otherwise
        use Docker.
      - ``True``: always use Docker.
      - ``False``: always run directly on the host (raises on a non-Linux host).

    Both paths return the same ``Termination`` variants.

    Args:
        binary_data: The raw bytes to execute.
        platform: The platform the bytes were built for.
        use_docker: Execution path override, as above.

    Returns:
        A :class:`RunResult` carrying stdout and how the process terminated.

    Raises:
        RuntimeError: If the target cannot run on this host, or if the
            container could not be built, started, or did not report a status.
    """
    match platform:
        case Platform.LINUX_X86:
            if use_docker is None:
                use_docker = host_platform() is not Platform.LINUX_X86
                logger.debug(
                    "run_binary: auto-resolved use_docker=%s (host=%s)",
                    use_docker,
                    host_description(),
                )

            if use_docker:
                return run_in_docker(binary_data)

            return run_on_host(binary_data, platform)
        case Platform.MAC_ARM:
            return run_on_host(binary_data, platform)
        case _:
            raise RuntimeError(f"Unsupported platform: {platform}")


def run_on_host(binary_data: bytes, platform: Platform) -> RunResult:
    """Run a binary directly on the host (no Docker).

    Requires an exact host/target match (see ``host_platform()``). For Linux
    x86_64 this is intended for cloud GPU environments (e.g. RunPod) where
    Docker-in-Docker is unavailable.

    Args:
        binary_data: The raw bytes to execute.
        platform: The platform the bytes were built for; must match the host.

    Returns:
        A :class:`RunResult`. ``subprocess`` encodes signal death as a negative
        return code, which is normalized to :class:`Signaled` here rather than
        being passed on as a bare integer.

    Raises:
        RuntimeError: If ``platform`` does not match the host.
    """
    if host_platform() is not platform:
        hint = (
            " Use run_binary(..., use_docker=True) instead."
            if platform is Platform.LINUX_X86
            else ""
        )

        raise RuntimeError(
            f"Platform mismatch: target '{platform}' cannot execute directly on "
            f"host '{host_description()}'.{hint}"
        )

    logger.debug("run_on_host: platform=%s", platform)

    with tempfile.TemporaryDirectory() as tmpdir:
        binary_path = Path(tmpdir) / "output.bin"
        binary_path.write_bytes(binary_data)

        make_binary_executable(binary_path)

        if platform is Platform.MAC_ARM:
            sign_binary(binary_path, platform)

        result = subprocess.run(
            [str(binary_path)],
            capture_output=True,
            check=False,
        )

        # subprocess reports signal death as -N and a normal exit as N.
        code = result.returncode
        termination = Signaled(signal=-code) if code < 0 else Exited(code=code)

        return RunResult(stdout=result.stdout, termination=termination)


# Keep this compatible with Debian bookworm Python 3.11. The supervisor
# records subprocess termination separately because shells fold signals into
# ordinary exit codes. Direct exec also reports unloadable files as OSError.
_CONTAINER_RUNNER = r"""
import os
import stat
import subprocess

bin_path = "/work/output.bin"
os.chmod(bin_path, 0o755)

try:
    # stdout/stderr are inherited, so the target's stdout still flows out
    # through the container's stdout as before.
    returncode = subprocess.run([bin_path]).returncode
except OSError:
    status = "X"
else:
    status = "S %d" % -returncode if returncode < 0 else "E %d" % returncode

with open("/work/status", "w") as fh:
    fh.write(status)
"""

_STATUS_FILE = "status"


def run_in_docker(binary_data: bytes, image: str | None = None) -> RunResult:
    """Run a Linux x86_64 binary inside a container and report its termination.

    stdout comes back over the container's stdout as usual; the termination
    status comes back through a file in the mounted work directory, because the
    container's own exit code cannot express the distinction (see the module
    docstring).

    The container has no network, 256 MiB of memory with no extra swap, at most
    64 processes and threads combined, and a 10 second execution deadline.
    It runs without root,
    capabilities or privilege escalation, with a read-only image filesystem.
    Its temporary work mount remains writable. This is not a sandbox for
    hostile code; output capture and the Docker daemon remain host resources.

    Args:
        binary_data: The raw bytes to execute.
        image: Image reference to run in. Defaults to the content-addressed tag
            from :func:`_image_tag`, building it if absent.

    Returns:
        A :class:`RunResult` carrying stdout and how the process terminated.

    Raises:
        RuntimeError: If Docker is unavailable, the image cannot be built, the
            target could not be executed, a memory limit or timeout was hit,
            no status was reported, or container cleanup failed.
    """
    image = image or _image_tag()
    logger.debug("run_in_docker: image=%s", image)

    try:
        _ensure_image(image)
    except FileNotFoundError:
        raise RuntimeError("Docker not found: is it installed and on PATH?") from None

    with tempfile.TemporaryDirectory() as tmp_dir:
        docker_work_dir = "/work"
        binary_path = Path(tmp_dir) / "output.bin"
        binary_path.write_bytes(binary_data)
        user_id = os.getuid() or 65534
        group_id = os.getgid() if os.getuid() else 65534
        if os.getuid() == 0:
            # Keep the mount private (0700) while letting a non-root supervisor
            # chmod the binary and write its status on root-run Linux hosts.
            os.chown(tmp_dir, user_id, group_id)
            os.chown(binary_path, user_id, group_id)

        container_name = f"binary-gen-{uuid.uuid4().hex}"
        try:
            try:
                result = subprocess.run(
                    [
                        "docker",
                        "run",
                        "--name",
                        container_name,
                        "--pull",
                        "never",
                        "--platform",
                        "linux/amd64",
                        "--network",
                        "none",
                        "--memory",
                        _DOCKER_MEMORY_LIMIT,
                        "--memory-swap",
                        _DOCKER_MEMORY_LIMIT,
                        "--pids-limit",
                        str(_DOCKER_PIDS_LIMIT),
                        "--user",
                        f"{user_id}:{group_id}",
                        "--cap-drop",
                        "ALL",
                        "--security-opt",
                        "no-new-privileges",
                        "--read-only",
                        "-v",
                        f"{tmp_dir}:{docker_work_dir}",
                        "-w",
                        docker_work_dir,
                        image,
                        "python3",
                        "-c",
                        _CONTAINER_RUNNER,
                    ],
                    capture_output=True,
                    check=False,
                    timeout=_DOCKER_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired:
                raise RuntimeError(
                    f"Container exceeded the {_DOCKER_TIMEOUT_SECONDS} second execution timeout."
                ) from None

            # Keep the stopped container until inspection so an OOM kill of
            # either the supervisor or its child cannot masquerade as an exit.
            state = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.OOMKilled}}", container_name],
                capture_output=True,
                check=False,
                timeout=_DOCKER_CONTROL_TIMEOUT_SECONDS,
            )
            if state.returncode != 0 or state.stdout.strip() not in {b"true", b"false"}:
                raise RuntimeError(
                    "Could not determine whether the container hit its memory limit."
                )
            if state.stdout.strip() == b"true":
                raise RuntimeError(f"Container exceeded its {_DOCKER_MEMORY_LIMIT} memory limit.")
            if result.returncode != 0:
                stderr = result.stderr.decode(errors="replace").strip()
                raise RuntimeError(
                    f"Container runner failed (docker exit {result.returncode}; "
                    f"137 means SIGKILL, possibly a resource limit or external kill). "
                    f"stderr: {stderr[:300]}"
                )

            status_path = Path(tmp_dir) / _STATUS_FILE
            try:
                # The child controls this path: a FIFO must not block cleanup.
                fd = os.open(status_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                try:
                    if not stat.S_ISREG(os.fstat(fd).st_mode):
                        raise RuntimeError("Container termination status is not a regular file.")
                    raw_status = os.read(fd, 16).decode("ascii")
                finally:
                    os.close(fd)
            except FileNotFoundError:
                stderr = result.stderr.decode(errors="replace").strip()
                raise RuntimeError(
                    "Container reported no termination status; it failed before or "
                    f"while running the binary. stderr: {stderr[:300]}"
                ) from None
            except (OSError, UnicodeError) as error:
                raise RuntimeError("Container termination status could not be read.") from error

            return RunResult(stdout=result.stdout, termination=_parse_status(raw_status))

        except subprocess.TimeoutExpired:
            raise RuntimeError("Docker container state inspection timed out.") from None
        finally:
            # subprocess.run's timeout kills only the CLI. Removing this exact
            # named container also stops its processes before the mount goes away.
            _remove_docker_container(container_name)


def _remove_docker_container(name: str) -> None:
    """Stop and remove this invocation's container, or expose a cleanup failure."""
    try:
        result = subprocess.run(
            ["docker", "rm", "--force", name],
            capture_output=True,
            check=False,
            timeout=_DOCKER_CONTROL_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(
            f"Could not stop/remove container {name}; it may still be running. "
            "Check Docker before running another binary."
        ) from error

    if result.returncode != 0 and b"No such container" not in result.stderr:
        raise RuntimeError(
            f"Could not stop/remove container {name}; it may still be running. "
            "Check Docker before running another binary."
        )


def _parse_status(raw: str) -> Termination:
    """Parse the container's status line into a :class:`Termination`.

    The wire format is deliberately tiny (``E <code>``, ``S <signal>``, or
    ``X`` for "could not execute at all") because it crosses a container
    boundary and anything richer would need a serializer on both sides.

    Args:
        raw: Contents of the status file written by ``_CONTAINER_RUNNER``.

    Returns:
        The parsed termination.

    Raises:
        RuntimeError: If the target could not be executed, or the status is
            not one of the three known forms.
    """
    status = raw.strip()
    if status == "X":
        raise RuntimeError("Container could not execute the binary (exec failed).")

    match = re.fullmatch(r"([ES]) ([0-9]{1,3})", status)
    if match is not None:
        kind, number = match.groups()
        try:
            return Exited(int(number)) if kind == "E" else Signaled(int(number))
        except ValueError:
            pass

    raise RuntimeError(f"Invalid container termination status: {raw!r}")


def check_docker() -> None:
    """Raise RuntimeError if Docker is not reachable.

    Raises:
        RuntimeError: If Docker is missing from PATH, unresponsive, or the
            daemon is not running.
    """
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            check=False,
            timeout=10,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "Docker not found on PATH. Install Docker Desktop and ensure it is running "
            "before executing binaries in a container."
        ) from None
    except subprocess.TimeoutExpired:
        raise RuntimeError("Docker info timed out. Is the Docker daemon running?") from None

    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(
            "Docker is not running. Start Docker Desktop before executing binaries.\n"
            f"docker info: {stderr[:300]}"
        )

    logger.info("Docker is running.")


def _image_tag() -> str:
    """Return the image reference, tagged by a hash of its Dockerfile.

    Content-addressing the tag is what makes a Dockerfile edit take effect:
    :func:`_ensure_image` only builds when the reference is absent, so a fixed
    tag would pin the very first build forever and silently keep serving a
    stale image. Hashing means the tag changes with the recipe, and the rebuild
    happens without anyone remembering to force one.

    Returns:
        An image reference of the form ``binary-gen-linux:<12 hex chars>``.
    """
    digest = hashlib.sha256(_DOCKERFILE.read_bytes()).hexdigest()[:12]

    return f"{IMAGE_NAME}:{digest}"


def _ensure_image(image: str) -> None:
    """Build the image if that exact reference isn't present locally.

    Args:
        image: The image reference to check for and build.

    Raises:
        RuntimeError: If Docker is not reachable.
        subprocess.CalledProcessError: If the build fails.
    """
    if image in _image_ready:
        return

    check_docker()

    probe = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
        check=False,
    )

    if probe.returncode != 0:
        logger.info("building Docker image %s", image)
        subprocess.run(
            [
                "docker",
                "build",
                "--platform",
                "linux/amd64",
                "-t",
                image,
                str(_DOCKERFILE_DIR),
            ],
            check=True,
        )

    _image_ready.add(image)
