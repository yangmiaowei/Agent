import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:
    pass

logger = logging.getLogger(__name__)

RETRYABLE_MARKERS = (
    "empty reply from server",
    "connection reset",
    "timed out",
    "timeout",
    "failed to connect",
    "couldn't connect to server",
    "could not resolve host",
    "unexpected disconnect",
    "error: rpc failed",
    "early eof",
    "promisor remote",
)

GIT_NETWORK_FLAGS = [
    "-c",
    "http.lowSpeedLimit=1000",
    "-c",
    "http.lowSpeedTime=600",
    "-c",
    "http.postBuffer=524288000",
]


def repo_dir_name(repo: str) -> str:
    return repo.replace("/", "__")


def _proxy_url() -> str | None:
    for key in (
        "https_proxy",
        "HTTPS_PROXY",
        "http_proxy",
        "HTTP_PROXY",
        "ALL_PROXY",
        "GIT_PROXY",
    ):
        value = os.environ.get(key)
        if value:
            return value
    return None


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    proxy = _proxy_url()
    if proxy:
        env.setdefault("https_proxy", proxy)
        env.setdefault("http_proxy", proxy)
        env.setdefault("HTTPS_PROXY", proxy)
        env.setdefault("HTTP_PROXY", proxy)
    return env


def _git_command_prefix() -> list[str]:
    flags = list(GIT_NETWORK_FLAGS)
    proxy = _proxy_url()
    if proxy:
        flags.extend(["-c", f"http.proxy={proxy}", "-c", f"https.proxy={proxy}"])
    return ["git", *flags]


def log_proxy_status() -> None:
    proxy = _proxy_url()
    if proxy:
        logger.info("Using git proxy: %s", proxy)
    else:
        logger.warning(
            "No git proxy configured. If GitHub is slow or unreachable, set "
            "https_proxy in your shell or .env (e.g. https_proxy=http://127.0.0.1:7890)."
        )


def _clone_urls(repo: str) -> list[str]:
    slug = repo_dir_name(repo)
    token = os.environ.get("GITHUB_TOKEN")
    auth = f"{token}@" if token else ""
    return [
        f"https://{auth}github.com/swe-bench-repos/{slug}.git",
        f"https://{auth}github.com/{repo}.git",
    ]


def _run_git(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*_git_command_prefix(), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=_git_env(),
    )


def _is_valid_repo(repo_path: Path) -> bool:
    if not (repo_path / ".git").exists():
        return False
    return _run_git(["rev-parse", "--git-dir"], cwd=repo_path).returncode == 0


def _current_head(repo_path: Path) -> str | None:
    result = _run_git(["rev-parse", "HEAD"], cwd=repo_path)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _remove_repo(repo_path: Path) -> None:
    if repo_path.exists():
        shutil.rmtree(repo_path)


def _is_retryable(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(marker in lowered for marker in RETRYABLE_MARKERS)


def _fetch_commit_once(repo_path: Path, base_commit: str) -> None:
    result = _run_git(
        ["fetch", "--depth", "1", "origin", base_commit],
        cwd=repo_path,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git fetch failed for {base_commit}: "
            f"{(result.stderr or result.stdout).strip()}"
        )

    result = _run_git(["checkout", "--force", base_commit], cwd=repo_path)
    if result.returncode != 0:
        raise RuntimeError(
            f"git checkout failed for {base_commit}: "
            f"{(result.stderr or result.stdout).strip()}"
        )


def _fetch_and_checkout(
    repo_path: Path,
    base_commit: str,
    *,
    max_attempts: int = 4,
) -> None:
    if _current_head(repo_path) == base_commit:
        logger.info("Repo already at %s", base_commit[:12])
        return

    last_error = "unknown error"
    for attempt in range(1, max_attempts + 1):
        try:
            logger.info(
                "Fetching commit %s (attempt %d/%d)",
                base_commit[:12],
                attempt,
                max_attempts,
            )
            _fetch_commit_once(repo_path, base_commit)
            return
        except RuntimeError as exc:
            last_error = str(exc)
            logger.warning("%s", last_error)
            if attempt < max_attempts and _is_retryable(last_error):
                delay = min(30, 2 ** attempt)
                logger.info("Retrying in %ds...", delay)
                time.sleep(delay)
                continue
            break

    raise RuntimeError(
        f"Failed to checkout {base_commit} in {repo_path}: {last_error}"
    )


def _clone_metadata(url: str, repo_path: Path) -> None:
    repo_path.parent.mkdir(parents=True, exist_ok=True)
    result = _run_git(
        [
            "clone",
            "--filter=blob:none",
            "--no-checkout",
            url,
            str(repo_path),
        ]
    )
    if result.returncode != 0:
        _remove_repo(repo_path)
        stderr = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"git clone failed for {url}: {stderr}")


def clone_repo(
    repo: str,
    repos_root: Path,
    base_commit: str,
    *,
    max_attempts: int = 4,
) -> Path:
    repos_root.mkdir(parents=True, exist_ok=True)
    repo_path = repos_root / repo_dir_name(repo)

    if _is_valid_repo(repo_path):
        logger.info("Reusing existing repo at %s", repo_path)
        _fetch_and_checkout(repo_path, base_commit, max_attempts=max_attempts)
        return repo_path

    if repo_path.exists():
        logger.warning("Removing incomplete repo at %s", repo_path)
        _remove_repo(repo_path)

    urls = _clone_urls(repo)
    last_error = "unknown error"

    for url in urls:
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(
                    "Cloning %s (attempt %d/%d)",
                    url,
                    attempt,
                    max_attempts,
                )
                _clone_metadata(url, repo_path)
                _fetch_and_checkout(repo_path, base_commit, max_attempts=max_attempts)
                return repo_path
            except RuntimeError as exc:
                last_error = str(exc)
                logger.warning("%s", last_error)
                if _is_valid_repo(repo_path):
                    # Metadata clone succeeded; only fetch/checkout failed.
                    # Keep the repo and retry checkout on the next attempt.
                    try:
                        _fetch_and_checkout(
                            repo_path,
                            base_commit,
                            max_attempts=max_attempts,
                        )
                        return repo_path
                    except RuntimeError as checkout_exc:
                        last_error = str(checkout_exc)
                else:
                    _remove_repo(repo_path)

                if attempt < max_attempts and _is_retryable(last_error):
                    delay = min(30, 2 ** attempt)
                    logger.info("Retrying in %ds...", delay)
                    time.sleep(delay)
                    continue
                break

    raise RuntimeError(
        f"Failed to clone {repo} at {base_commit} after trying {len(urls)} sources: {last_error}"
    )


def reset_repo(repo_path: Path, base_commit: str) -> None:
    result = _run_git(["reset", "--hard", base_commit], cwd=repo_path)
    if result.returncode != 0:
        raise RuntimeError(
            f"git reset failed for {base_commit}: "
            f"{(result.stderr or result.stdout).strip()}"
        )

    result = _run_git(["clean", "-fdxq"], cwd=repo_path)
    if result.returncode != 0:
        raise RuntimeError(
            f"git clean failed: {(result.stderr or result.stdout).strip()}"
        )


def prepare_instance_workspace(
    instance: dict,
    repos_root: Path,
) -> Path:
    log_proxy_status()
    repo_path = clone_repo(
        instance["repo"],
        repos_root,
        instance["base_commit"],
    )
    reset_repo(repo_path, instance["base_commit"])
    return repo_path
