import abc

from src.registry.tool_registry import ToolRegistry


class Plugin(abc.ABC):
    name: str

    @abc.abstractmethod
    def register(self, registry: ToolRegistry, plugin_config: dict) -> None:
        pass
