import json
import os
from datetime import datetime
from pathlib import Path

from src.workspace import LOGS_DIR, TEST_LOGS_DIR


def _json_default(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class JsonLogger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, data, *, scope: str | None = None):
        record = {
            "timestamp": datetime.now().isoformat(),
            "data": data,
        }
        if scope:
            record["scope"] = scope

        with open(self.path, "a", encoding="utf8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=_json_default) + "\n")


class SessionEventWriter:
    """Scoped writer for a single chronological event stream."""

    def __init__(self, logger: JsonLogger, scope: str = "main"):
        self._logger = logger
        self.scope = scope

    def log(self, data):
        scope = self.scope if self.scope != "main" else None
        self._logger.log(data, scope=scope)


class LogSession:
    """One conversation session: all events in a single chronological file."""

    def __init__(self, session_dir: Path, scope: str = "main"):
        self.dir = Path(session_dir)
        self.scope = scope
        self.dir.mkdir(parents=True, exist_ok=True)
        self._events = JsonLogger(self.dir / "events.jsonl")
        self._writer = SessionEventWriter(self._events, scope=scope)

    @classmethod
    def create(cls, *, test: bool = False) -> "LogSession":
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        root = TEST_LOGS_DIR if test else LOGS_DIR
        name = f"test_{ts}" if test else f"session_{ts}"
        return cls(root / name)

    def subsession(self, name: str) -> "LogSession":
        return LogSession(self.dir / "subagents" / name, scope=f"subagent/{name}")

    @property
    def events(self) -> SessionEventWriter:
        return self._writer


def is_test_context() -> bool:
    return os.environ.get("PYTEST_CURRENT_TEST") is not None


def log_message(logger, msg):
    if not logger:
        return
    role = msg["role"]
    content = msg["content"]
    if isinstance(content, list):
        for block in content:
            logger.log({"role": role, "content": block})
    else:
        logger.log({"role": role, "content": content})
