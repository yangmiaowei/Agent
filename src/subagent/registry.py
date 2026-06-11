"""Backward-compatible re-exports. Prefer src.registry."""

from src.plugins.core_tools_plugin import CORE_TOOL_CLASSES
from src.registry.subagent_types import (
    DEFAULT_TYPES,
    SubagentTypeDef,
    load_subagent_types,
)

TOOL_CLASS_BY_NAME = {cls().name: cls for cls in CORE_TOOL_CLASSES}

__all__ = [
    "CORE_TOOL_CLASSES",
    "DEFAULT_TYPES",
    "SubagentTypeDef",
    "TOOL_CLASS_BY_NAME",
    "load_subagent_types",
]
