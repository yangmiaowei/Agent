from pathlib import Path

_DEFAULT_WORKDIR = Path.cwd() / "WORKDIR"
_workdir: Path | None = None


def get_workdir() -> Path:
    path = _workdir if _workdir is not None else _DEFAULT_WORKDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def set_workdir(path: Path) -> None:
    global _workdir
    _workdir = Path(path).resolve()
    _workdir.mkdir(parents=True, exist_ok=True)


def reset_workdir() -> None:
    global _workdir
    _workdir = None


# Backward-compatible alias
WORKDIR = get_workdir()

LOGS_DIR = _DEFAULT_WORKDIR / "logs"
TEST_LOGS_DIR = LOGS_DIR / "tests"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
