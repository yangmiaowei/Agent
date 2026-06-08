import abc
from typing import Any, Dict
from pathlib import Path

WORKDIR = Path.cwd()


class BaseTool(abc.ABC):
    """
    抽象工具基类，兼容 Anthropic / Claude Tools 格式
    """

    # 必填属性（子类必须定义）
    name: str
    description: str
    input_schema: Dict[str, Any]

    def __init__(self):
        if not hasattr(self, "name") or not self.name:
            raise ValueError("Tool must define 'name'")
        if not hasattr(self, "description") or not self.description:
            raise ValueError("Tool must define 'description'")
        if not hasattr(self, "input_schema") or not self.input_schema:
            raise ValueError("Tool must define 'input_schema'")

    # ===== 核心执行逻辑 =====
    @abc.abstractmethod
    def run(self, **kwargs) -> str:
        """
        执行工具逻辑
        """
        pass

    # ===== 校验输入 =====
    def validate(self, kwargs: dict):
        """
        简单 JSON Schema 校验（只支持 required + string/int）
        """
        required = self.input_schema.get("required", [])
        props = self.input_schema.get("properties", {})

        # 检查必填
        for r in required:
            if r not in kwargs:
                raise ValueError(f"Missing required field: {r}")

        # 类型简单检查
        for k, v in kwargs.items():
            if k in props:
                expected_type = props[k].get("type")
                if expected_type == "string" and not isinstance(v, str):
                    raise TypeError(f"{k} should be string")
                if expected_type == "integer" and not isinstance(v, int):
                    raise TypeError(f"{k} should be integer")

    # ===== 输出 schema 给 agent loop =====
    def schema(self) -> Dict[str, Any]:
        """
        返回 Anthropic / Claude Tools 格式
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema
        }


def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()  # str -> Path
    # .resolve()：把路径“还原成真实存在的位置”
    # 例：
    # WORKDIR = /app/workspace
    # p = "../secret.txt"

    # (WORKDIR / p)         # /app/workspace/../secret.txt
    # .resolve()            # /app/secret.txt   ← 真正位置
    if not path.is_relative_to(WORKDIR):  # 检查这个路径是不是在 WORKDIR 里面
        raise ValueError(f"Path escapes workspace: {p}")
    return path