from src.tools.base_tool import BaseTool, safe_path
from src.tools.tool_manager import tool

@tool
class EditFile(BaseTool):
    name = "edit_file"
    description = "Replace exact text in file."
    input_schema = {
        "type": "object", 
        "properties": {
            "path": {"type": "string"}, 
            "old_text": {"type": "string"}, 
            "new_text": {"type": "string"}
        }, 
        "required": ["path", "old_text", "new_text"]
    }

    def run(self, **kwargs) -> str:
        # 校验参数
        self.validate(kwargs)

        path = kwargs["path"]
        old_text = kwargs["old_text"]
        new_text = kwargs["new_text"]

        try:
            fp = safe_path(path)
            content = fp.read_text()
            if old_text not in content:
                return f"Error: Text not found in {path}"
            fp.write_text(content.replace(old_text, new_text, 1))
            return f"Edited {path}"
        except Exception as e:
            return f"Error: {e}" 