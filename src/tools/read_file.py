from src.tools.base_tool import BaseTool, safe_path


class ReadFile(BaseTool):
    name = "read_file"
    description = "Read file contents."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "offset": {"type": "integer"},
            "limit": {"type": "integer"},
        },
        "required": ["path"],
    }

    def run(self, **kwargs) -> str:
        self.validate(kwargs)

        path = kwargs["path"]
        offset = max(0, int(kwargs.get("offset") or 0))
        limit = kwargs.get("limit")

        try:
            text = safe_path(path).read_text()
            lines = text.splitlines()
            total = len(lines)
            if offset:
                lines = lines[offset:]
            if limit is not None and limit < len(lines):
                remaining = len(lines) - limit
                lines = lines[:limit] + [f"... ({remaining} more lines)"]
            header = f"# {path} (lines {offset + 1}-{offset + len(lines)} of {total})\n"
            return header + "\n".join(lines)[:50000]
        except Exception as e:
            return f"Error: {e}"
