
import os
from typing import List, Dict
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

# Custom base URL (e.g. BigModel): SDK prefers ANTHROPIC_AUTH_TOKEN over API_KEY;
# stale AUTH_TOKEN causes 401 even when ANTHROPIC_API_KEY is valid.
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL = os.getenv("MODEL")

from src.prompts.system_prompt import SYSTEM_PROMPT
from src.tools.tool_manager import ToolManager

class AnthropicClient:
    def __init__(
        self,
        tools: ToolManager,
        api_key: str = ANTHROPIC_API_KEY,
        base_url: str = ANTHROPIC_BASE_URL,
        model: str = MODEL,
    ):
        self.tools = tools
        self.client = Anthropic(api_key=api_key, base_url=base_url)
        self.model = model

    def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 8000,
        tools: ToolManager = None,
        system: str = None,
    ) -> str:
        manager = tools or self.tools
        tool_schemas = manager.list_tools()
        # print("Tools:", tool_schemas)
        response = self.client.messages.create(
            model=self.model,
            system=system or SYSTEM_PROMPT,
            messages=messages,
            tools=tool_schemas,
            max_tokens=max_tokens
        )
        # print(response)
        return response

# messages = [{"role": "user", "content": "Create a file called greet.py with a greet(name) function"}]
# response = client.messages.create(
#             model=MODEL, system=SYSTEM, messages=messages,
#             tools=TOOLS, max_tokens=8000,
#         )
# print(response)
# print(response.content)

# Message(
#     id='msg_29a45bc2-16b', 
#     container=None, 
#     content=[
#         ToolUseBlock(
#             id='tooluse_exqfLG4ABdtKuouib1phWp', 
#             caller=None, 
#             input={'command': 'cat > /Users/yangmw/Personal/Works/Agent/greet.py << \'EOF\'\ndef greet(name):\n    return f"Hello, {name}!"\nEOF'}, 
#             name='bash', 
#             type='tool_use'
#         )
#     ], 
#     model='claude-sonnet-4-6', 
#     role='assistant', 
#     stop_reason='tool_use', 
#     stop_sequence=None, 
#     type='message', 
#     usage=Usage(
#         cache_creation=None, 
#         cache_creation_input_tokens=140, 
#         cache_read_input_tokens=28, 
#         inference_geo=None, 
#         input_tokens=2624, 
#         output_tokens=53, 
#         server_tool_use=None, 
#         service_tier=None, 
#         cache_write_tokens=140)
# )