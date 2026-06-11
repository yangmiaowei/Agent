from src.tools.base_tool import BaseTool, safe_path


class LoadSkill(BaseTool):
    name = "load_skill"
    description = "Load specialized knowledge by name."
    input_schema = {
        "type": "object", 
        "properties": {
            "name": {
                "type": "string", 
                "description": "Skill name to load"
            }
        }, 
        "required": ["name"]
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