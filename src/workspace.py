from pathlib import Path

WORKDIR = Path.cwd() / "WORKDIR"
WORKDIR.mkdir(parents=True, exist_ok=True)

LOGS_DIR = WORKDIR / "logs"
TEST_LOGS_DIR = LOGS_DIR / "tests"
