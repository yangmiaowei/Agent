import abc
from dataclasses import dataclass
from typing import Any

from src.tools.tool_manager import ToolManager


@dataclass
class BuildContext:
    main_tm: ToolManager
    core_tools: list
    config: dict[str, Any]


class Plugin(abc.ABC):
    name: str

    @abc.abstractmethod
    def setup(self, ctx: BuildContext, plugin_config: dict) -> None:
        pass
