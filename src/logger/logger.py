import json


class JsonLogger:
    def __init__(self, path="agent_log.jsonl"):
        self.path = path

    def log(self, data):
        with open(self.path, "a", encoding="utf8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")