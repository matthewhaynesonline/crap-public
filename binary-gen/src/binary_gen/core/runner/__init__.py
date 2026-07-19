import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from binary_gen.core import make_binary_executable, sign_binary
from binary_gen.core.platform import Platform, host_description, host_platform

_DOCKERFILE_DIR = Path(__file__).parent
IMAGE = "binary-gen-linux"

logger = logging.getLogger(__name__)

# Caches images that have already been confirmed present or built this process
# lifetime, avoiding a `docker image inspect` subprocess on every run_in_docker
# call in tight eval loops.
_image_ready: set[str] = set()


@dataclass
class RunResult:
    stdout: bytes
    exit_code: int


def check_docker() -> None:
    """
    Raise RuntimeError if Docker is not reachable.

    Call this early in any workflow that depends on Docker execution — fail fast
    rather than discovering the daemon is missing mid-operation. The training
    eval callback calls this before starting a training run so Docker problems
    surface immediately rather than mid-run when the first eval fires.
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
            "before training — the eval callback requires it for behavioral binary execution."
        ) from None
    except subprocess.TimeoutExpired:
        raise RuntimeError("Docker info timed out. Is the Docker daemon running?") from None

    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(
            "Docker is not running. Start Docker Desktop before training.\n"
            f"docker info: {stderr[:300]}"
        )

    logger.info("Docker is running.")


def run_binary(
    binary_data: bytes,
    platform: Platform,
    *,
    use_docker: bool | None = None,
) -> RunResult:
    """Execute a binary for ``platform`` and return its stdout and exit code.

    use_docker semantics (Linux x86_64 targets only — macOS targets always
    run on the host):
      - None (auto): run directly when the host is Linux x86_64, otherwise
        use Docker. This makes RunPod-style Linux hosts "just work" without
        remembering --no-docker.
      - True: always use Docker.
      - False: always run directly on the host (raises on a non-Linux host).
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

    Requires an exact host/target match (see host_platform()). For Linux
    x86_64 this is intended for cloud GPU environments (e.g. RunPod) where
    Docker-in-Docker is unavailable.
    """
    if host_platform() is not platform:
        hint = (
            " Use Docker instead (use_docker=True / --docker)."
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

        return RunResult(stdout=result.stdout, exit_code=result.returncode)


def run_in_docker(binary_data: bytes, image: str = IMAGE) -> RunResult:
    """
    Runs a Linux x86_64 binary inside a Docker container.
    Returns stdout and exit code without raising on non-zero exit.
    """
    logger.debug("run_in_docker: image=%s", image)

    try:
        _ensure_image(image)
    except FileNotFoundError:
        raise RuntimeError("Docker not found — is it installed and on PATH?") from None

    with tempfile.TemporaryDirectory() as tmp_dir:
        bin_name = "output.bin"

        host_bin_path = Path(tmp_dir) / bin_name
        host_bin_path.write_bytes(binary_data)

        docker_work_dir = "/work"
        docker_bin_path = f"{docker_work_dir}/{bin_name}"

        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--platform",
                "linux/amd64",
                "-v",
                f"{tmp_dir}:{docker_work_dir}",
                "-w",
                docker_work_dir,
                image,
                "bash",
                "-c",
                f"chmod +x {docker_bin_path} && {docker_bin_path}",
            ],
            capture_output=True,
            check=False,
        )

        return RunResult(stdout=result.stdout, exit_code=result.returncode)


def _ensure_image(image: str = IMAGE) -> None:
    """Builds the Docker image if it doesn't already exist."""
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
