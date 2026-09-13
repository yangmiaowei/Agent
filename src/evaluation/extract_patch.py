import subprocess
from pathlib import Path


def extract_patch(repo_path: Path) -> str:
    result = subprocess.run(
        ["git", "diff", "--no-color"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git diff failed")
    return result.stdout.strip()
