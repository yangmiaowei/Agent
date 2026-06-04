import abc


class BaseTool(abc.ABC):
    """所有工具的基类，定义接口"""
    name_for_human: str = ""
    name_for_model: str = ""
    description_for_model: str = ""
    parameters: list = []

    @abc.abstractmethod
    def run(self, **kwargs):
        pass