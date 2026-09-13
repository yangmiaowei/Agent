"""Thin wrapper around the official SWE-bench harness.

The harness writes its artifacts relative to the process working directory:

    <cwd>/{model_name}.{run_id}.json                      aggregate report
    <cwd>/logs/run_evaluation/{run_id}/{model}/{iid}/report.json   per instance

so it is invoked with `cwd` pointing inside the run directory, keeping every
artifact for a run together.

On Apple Silicon the official flow still applies: the prebuilt
`swebench/sweb.eval.x86_64.*` images run under Docker Desktop's amd64
emulation. But the harness pulls them via docker-py without a platform
argument, which fails on an arm64 host with "no matching manifest for
linux/arm64/v8". Pre-pull them so the harness finds them locally and never
pulls:

    docker pull --platform linux/amd64 swebench/sweb.eval.x86_64.<iid>:latest

where `<iid>` is the instance id with `__` replaced by `_1776_`.

Instance images are multi-GB each. After grading, remove them with
`remove_instance_images` (wired into `run_eval` by default) so a 24-case
suite does not fill the disk.
"""

import json
import logging
import platform
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

HARNESS_MODULE = "swebench.harness.run_evaluation"

#: Docker Hub namespace holding the official prebuilt evaluation images.
PREBUILT_NAMESPACE = "swebench"
#: Sentinel the harness understands as "no namespace, build images locally".
LOCAL_NAMESPACE = "none"
#: Platform tag for official prebuilt images.
PREBUILT_PLATFORM = "linux/amd64"


def default_namespace() -> str:
    """Always prefer official prebuilt images.

    They are x86_64-only but run fine on Apple Silicon via Docker Desktop
    emulation. Use `--namespace none` only when you intentionally want to
    build from scratch: upstream `make_test_spec` hardcodes `arch="x86_64"`,
    so a local build on arm64 goes through qemu and is far slower than
    pulling.
    """
    return PREBUILT_NAMESPACE


class HarnessUnavailable(RuntimeError):
    """The harness cannot run in this environment."""


def check_prerequisites() -> None:
    """Fail early with an actionable message instead of deep inside Docker."""
    try:
        import swebench  # noqa: F401
    except ImportError as exc:
        raise HarnessUnavailable(
            "The `swebench` package is not importable by "
            f"{sys.executable}. Install it with `pip install -e .` from a "
            "SWE-bench checkout, and make sure you run this with the same "
            "interpreter."
        ) from exc

    if shutil.which("docker") is None:
        raise HarnessUnavailable(
            "`docker` was not found on PATH. The SWE-bench harness evaluates "
            "each instance inside a container."
        )

    probe = subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        raise HarnessUnavailable(
            "The Docker daemon is not reachable. Start Docker Desktop and "
            f"retry. docker reported: {(probe.stderr or probe.stdout).strip()[:300]}"
        )


def report_path(work_dir: Path, model_name: str, run_id: str) -> Path:
    return work_dir / f"{model_name.replace('/', '__')}.{run_id}.json"


def instance_report_path(
    work_dir: Path, run_id: str, model_name: str, instance_id: str
) -> Path:
    return (
        work_dir
        / "logs"
        / "run_evaluation"
        / run_id
        / model_name.replace("/", "__")
        / instance_id
        / "report.json"
    )


def instance_image_name(
    instance_id: str, *, namespace: str = PREBUILT_NAMESPACE
) -> str:
    """Docker Hub tag for one instance's official evaluation image.

    Matches SWE-bench's `TestSpec.instance_image_key` for the prebuilt
    x86_64 images (the `__` in the instance id becomes `_1776_`).
    """
    if namespace == LOCAL_NAMESPACE:
        raise ValueError(
            "Locally built images use a different naming scheme; "
            "instance_image_name only covers the prebuilt swebench/* tags."
        )
    return f"{namespace}/sweb.eval.x86_64.{instance_id.replace('__', '_1776_')}:latest"


def _is_arm64() -> bool:
    return platform.machine().lower() in ("arm64", "aarch64")


def needs_platform_prepull() -> bool:
    """True when the harness cannot pull prebuilt images by itself."""
    return _is_arm64()


def image_present(image: str) -> bool:
    return (
        subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
        ).returncode
        == 0
    )


def prepull_instance_images(
    instance_ids: list[str],
    *,
    namespace: str = PREBUILT_NAMESPACE,
    platform_name: str = PREBUILT_PLATFORM,
) -> list[str]:
    """Pull missing prebuilt images with an explicit platform.

    Returns the list of image names that were pulled (already-local images
    are skipped). Raises RuntimeError on the first failed pull.
    """
    pulled: list[str] = []
    for instance_id in instance_ids:
        image = instance_image_name(instance_id, namespace=namespace)
        if image_present(image):
            logger.info("Image already local: %s", image)
            continue
        logger.info("Pulling %s (%s)", image, platform_name)
        result = subprocess.run(
            ["docker", "pull", f"--platform={platform_name}", image],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()[-500:]
            raise RuntimeError(f"Failed to pull {image}: {detail}")
        pulled.append(image)
    return pulled


def remove_instance_images(
    instance_ids: list[str],
    *,
    namespace: str = PREBUILT_NAMESPACE,
) -> list[str]:
    """Force-remove prebuilt instance images. Missing images are ignored.

    Returns the list of image names that were actually removed.
    """
    removed: list[str] = []
    for instance_id in instance_ids:
        image = instance_image_name(instance_id, namespace=namespace)
        if not image_present(image):
            continue
        result = subprocess.run(
            ["docker", "rmi", "-f", image],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            removed.append(image)
            logger.info("Removed image %s", image)
        else:
            logger.warning(
                "Could not remove %s: %s",
                image,
                (result.stderr or result.stdout).strip()[:300],
            )
    return removed


def run_harness_evaluation(
    *,
    predictions_path: Path,
    dataset_name: str = "princeton-nlp/SWE-bench_Lite",
    split: str = "test",
    run_id: str,
    work_dir: Path,
    max_workers: int = 4,
    instance_ids: list[str] | None = None,
    timeout: int = 1800,
    cache_level: str = "env",
    namespace: str | None = None,
    extra_args: list[str] | None = None,
) -> int:
    work_dir.mkdir(parents=True, exist_ok=True)
    namespace = namespace or default_namespace()
    cmd = [
        sys.executable,
        "-m",
        HARNESS_MODULE,
        "--dataset_name",
        dataset_name,
        "--split",
        split,
        # Absolute: the harness runs with cwd=work_dir.
        "--predictions_path",
        str(Path(predictions_path).resolve()),
        "--max_workers",
        str(max_workers),
        "--run_id",
        run_id,
        "--timeout",
        str(timeout),
        "--cache_level",
        cache_level,
        "--namespace",
        namespace,
    ]
    if instance_ids:
        cmd.extend(["--instance_ids", *instance_ids])
    if extra_args:
        cmd.extend(extra_args)

    if namespace == LOCAL_NAMESPACE:
        logger.warning(
            "Building evaluation images locally (namespace=none). This is slow; "
            "prefer the default prebuilt swebench/* images."
        )
    elif platform.machine().lower() in ("arm64", "aarch64"):
        logger.info(
            "arm64 host: prebuilt x86_64 images run under Docker amd64 "
            "emulation, but the harness cannot pull them itself. Pre-pull "
            "missing images with `docker pull --platform linux/amd64` or "
            "grading will fail with 'no matching manifest'."
        )

    logger.info("Running harness in %s: %s", work_dir, " ".join(cmd))
    return subprocess.run(cmd, cwd=work_dir).returncode


def load_report(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def load_instance_report(
    work_dir: Path, run_id: str, model_name: str, instance_id: str
) -> dict | None:
    """Per-instance grading detail, or None when the harness produced none."""
    path = instance_report_path(work_dir, run_id, model_name, instance_id)
    if not path.exists():
        return None
    with open(path) as f:
        data = json.load(f)
    # The file is keyed by instance id.
    return data.get(instance_id, data)
