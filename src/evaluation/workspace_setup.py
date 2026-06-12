import os
import subprocess
from pathlib import Path


def repo_dir_name(repo: str) -> str:
    return repo.replace("/", "__")


def clone_repo(repo: str, repos_root: Path) -> Path:
    repos_root.mkdir(parents=True, exist_ok=True)
    repo_path = repos_root / repo_dir_name(repo)
    if repo_path.exists():
        return repo_path

    token = os.environ.get("GITHUB_TOKEN", "git")
    url = (
        f"https://{token}@github.com/swe-bench-repos/"
        f"{repo_dir_name(repo)}.git"
    )
    subprocess.run(
        ["git", "clone", url, str(repo_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return repo_path


def reset_repo(repo_path: Path, base_commit: str) -> None:
    subprocess.run(
        ["git", "reset", "--hard", base_commit],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "clean", "-fdxq"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )


def prepare_instance_workspace(
    instance: dict,
    repos_root: Path,
) -> Path:
    repo_path = clone_repo(instance["repo"], repos_root)
    reset_repo(repo_path, instance["base_commit"])
    return repo_path
