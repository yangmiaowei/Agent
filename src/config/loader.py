import json
import os
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "agent_config.json"


def load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        config = json.load(f)

    subagent = config.setdefault("plugins", {}).setdefault("subagent", {})
    env_enabled = os.getenv("SUBAGENT_ENABLED")
    if env_enabled is not None:
        subagent["enabled"] = env_enabled.lower() in ("1", "true", "yes")

    env_types = os.getenv("SUBAGENT_TYPES")
    if env_types:
        subagent["enabled_types"] = [t.strip() for t in env_types.split(",") if t.strip()]

    return config
