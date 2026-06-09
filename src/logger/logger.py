import json


def _json_default(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class JsonLogger:
    def __init__(self, path="agent_log.jsonl"):
        self.path = path

    def log(self, data):
        with open(self.path, "a", encoding="utf8") as f:
            f.write(json.dumps(data, ensure_ascii=False, default=_json_default) + "\n")


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