import json
from pathlib import Path
from datetime import datetime


def _json_default(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class JsonLogger:
    def __init__(self, workdir=None):
        self.workdir = Path(workdir) if workdir else Path.cwd() / "WORKDIR"
        self.workdir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = self.workdir / f"agent_log_{ts}.jsonl"

    def log(self, data):
        record = {
            "timestamp": datetime.now().isoformat(),
            "data": data
        }

        with open(self.path, "a", encoding="utf8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=_json_default) + "\n")


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