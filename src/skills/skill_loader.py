"""Backward-compatible re-export. Prefer src.runtime.skill_loader."""

from pathlib import Path

from src.runtime.skill_loader import SkillLoader
from src.workspace import WORKDIR

SKILL_DIR = Path(__file__).parent

__all__ = ["SkillLoader", "SKILL_DIR", "WORKDIR"]
