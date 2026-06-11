import os
from typing import List, Dict

from anthropic import Anthropic
from dotenv import load_dotenv

from src.prompts.system_prompt import SYSTEM_PROMPT

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL = os.getenv("MODEL")


class AnthropicClient:
    def __init__(
        self,
        api_key: str = ANTHROPIC_API_KEY,
        base_url: str = ANTHROPIC_BASE_URL,
        model: str = MODEL,
    ):
        self.client = Anthropic(api_key=api_key, base_url=base_url)
        self.model = model

    def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 8000,
        tools=None,
        system: str = None,
    ) -> str:
        if tools is None:
            raise ValueError("tools (ToolView or ToolManager) is required")
        tool_schemas = tools.list_tools()
        response = self.client.messages.create(
            model=self.model,
            system=system or SYSTEM_PROMPT,
            messages=messages,
            tools=tool_schemas,
            max_tokens=max_tokens,
        )
        return response
