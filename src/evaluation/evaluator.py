import subprocess
import sys
from pathlib import Path


def run_harness_evaluation(
    *,
    predictions_path: Path,
    dataset_name: str = "princeton-nlp/SWE-bench_Lite",
    split: str = "test",
    run_id: str,
    max_workers: int = 4,
    instance_ids: list[str] | None = None,
    timeout: int = 1800,
) -> int:
    cmd = [
        sys.executable,
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        dataset_name,
        "--split",
        split,
        "--predictions_path",
        str(predictions_path),
        "--max_workers",
        str(max_workers),
        "--run_id",
        run_id,
        "--timeout",
        str(timeout),
    ]
    if instance_ids:
        cmd.extend(["--instance_ids", *instance_ids])
    return subprocess.run(cmd).returncode
