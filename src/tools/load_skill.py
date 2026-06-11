from typing import ClassVar, Optional

from src.runtime.skill_loader import SkillLoader
from src.tools.base_tool import BaseTool


class LoadSkill(BaseTool):
    name = "load_skill"
    description = "Load specialized knowledge by name."
    input_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill name to load",
            }
        },
        "required": ["name"],
    }

    _skill_loader: ClassVar[Optional[SkillLoader]] = None

    @classmethod
    def configure(cls, skill_loader: SkillLoader) -> None:
        cls._skill_loader = skill_loader

    def run(self, **kwargs) -> str:
        self.validate(kwargs)
        if self._skill_loader is None:
            return "Error: Skill loader is not configured."
        return self._skill_loader.get_content(kwargs["name"])
