import json
import os
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "agent_config.json"


def _parse_bool(value: str) -> bool:
    return value.lower() in ("1", "true", "yes")


def load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        config = json.load(f)

    runtime = config.setdefault("runtime", {})
    subagent = config.setdefault("plugins", {}).setdefault("subagent", {})

    env_mode = os.getenv("AGENT_MODE")
    if env_mode:
        runtime["mode"] = env_mode.strip()

    env_safe = os.getenv("SAFE_MODE")
    if env_safe is not None:
        runtime["safe_mode"] = _parse_bool(env_safe)

    env_skills = os.getenv("SKILLS_ENABLED")
    if env_skills is not None:
        runtime["skills_enabled"] = _parse_bool(env_skills)

    env_enabled = os.getenv("SUBAGENT_ENABLED")
    if env_enabled is not None:
        subagent["enabled"] = _parse_bool(env_enabled)

    env_types = os.getenv("SUBAGENT_TYPES")
    if env_types:
        subagent["enabled_types"] = [t.strip() for t in env_types.split(",") if t.strip()]

    return config
