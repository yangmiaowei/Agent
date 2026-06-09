from src.tools.base_tool import BaseTool, safe_path


class ReadFile(BaseTool):
    name = "read_file"
    description = "Read file contents."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "limit":{"type": "integer"}
        },
        "required": ["path"]
    }

    def run(self, **kwargs) -> str:
        # 校验参数
        self.validate(kwargs)

        path = kwargs["path"]
        limit = kwargs.get("limit")

        try:
            text = safe_path(path).read_text()  # 文件内容一次性读成一个字符串
            lines = text.splitlines()  # 按换行符拆分字符串，返回一个按行分割的列表
            if limit and limit < len(lines):
                lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
            return "\n".join(lines)[:50000]
        except Exception as e:
            return f"Error: {e}"