#!/usr/bin/env python3
# Harness: the loop -- the model's first connection to the real world.
"""
s01_agent_loop.py - The Agent Loop

The entire secret of an AI coding agent in one pattern:

    while stop_reason == "tool_use":
        response = LLM(messages, tools)
        execute tools
        append results

    +----------+      +-------+      +---------+
    |   User   | ---> |  LLM  | ---> |  Tool   |
    |  prompt  |      |       |      | execute |
    +----------+      +---+---+      +----+----+
                          ^               |
                          |   tool_result |
                          +---------------+
                          (loop continues)

This is the core loop: feed tool results back to the model
until the model decides to stop. Production agents layer
policy, hooks, and lifecycle controls on top.
"""

import os
import subprocess

# 修复 macOS 终端里 Python 输入中文 / 特殊字符 / 退格键异常的问题
try:
    import readline
    # #143 UTF-8 backspace fix for macOS libedit
    readline.parse_and_bind('set bind-tty-special-chars off')
    readline.parse_and_bind('set input-meta on')
    readline.parse_and_bind('set output-meta on')
    readline.parse_and_bind('set convert-meta off')
    readline.parse_and_bind('set enable-meta-keybindings on')
except ImportError:
    pass

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

print(os.getenv("ANTHROPIC_API_KEY"))

client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"), api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = os.environ["MODEL_ID"]

SYSTEM = f"You are a coding agent at {os.getcwd()}. Use bash to solve tasks. Act, don't explain."

TOOLS = [{
    "name": "bash",
    "description": "Run a shell command.",
    "input_schema": {
        "type": "object",
        "properties": {  # 定义有哪些参数
            "command": {"type": "string"}  # command 必须是字符串
        },
        "required": ["command"]
    }
}]

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



def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(  # 启动一个子进程执行 command，等它执行完，然后返回结果对象 r
                command, 
                shell=True,  # 通过 shell（比如 /bin/bash）来执行命令，有命令注入风险
                cwd=os.getcwd(),  # 指定命令执行的“当前目录”，等价于：cd 当前目录 && 执行命令
                capture_output=True,  # 把 stdout 和 stderr 都抓回来，否则输出会直接打印到终端 拿不到结果
                text=True, #把输出从 bytes → 字符串 否则你拿到的是：b'hello\n'，加了之后变成："hello\n"
                timeout=120  # 防止：死循环，卡死，挂住 agent
            )
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
         return "Error: Timeout (120s)"


# -- The core pattern: a while loop that calls tools until the model stops --
def agent_loop(messages: list):
    while True:
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000
        )
        # Append assistant turn
        messages.append({"role": "assistant", "content": response.content})
        # If the model didn't call a tool, we're done
        if response.stop_reason != "tool_use":
            return
        # Execute each tool call, collect results
        results = []
        for block in response.content:
            if block.type == "tool_use":
                print(f"\033[33m$ {block.input['command']}\033[0m")
                output = run_bash(block.input["command"])
                print(output[:200])
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output
                })
        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    history = []
    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break

        history.append({"role": "user", "content": query})
        agent_loop(history)

        print("\n===== FULL MESSAGES DEBUG =====")
        for i, m in enumerate(history):
            print(f"\n--- message {i} ---")
            print(m)

        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)
        print()



# s01 >> Create a file called greet.py with a greet(name) function
# Message(id='msg_01HrdkxK2JQpVQgXVhJuPdNP', container=None, content=[ToolUseBlock(id='toolu_01PAiYrbm874JjH7VKJAskh4', caller=DirectCaller(type='direct'), input={'command': 'cat << \'EOF\' > /Users/yangmw/Personal/Works/Agent/greet.py\ndef greet(name):\n    """Greet a person by name."""\n    return f"Hello, {name}!"\nEOF'}, name='bash', type='tool_use')], model='claude-sonnet-4-6', role='assistant', stop_reason='tool_use', stop_sequence=None, type='message', usage=Usage(cache_creation=CacheCreation(ephemeral_1h_input_tokens=0, ephemeral_5m_input_tokens=0), cache_creation_input_tokens=0, cache_read_input_tokens=0, inference_geo='not_available', input_tokens=602, output_tokens=106, server_tool_use=None, service_tier='standard'), stop_details=None)
# $ cat << 'EOF' > /Users/yangmw/Personal/Works/Agent/greet.py
# def greet(name):
#     """Greet a person by name."""
#     return f"Hello, {name}!"
# EOF
# (no output)
# Message(id='msg_017MtqABC4HgZoKMFqSuyoLa', container=None, content=[TextBlock(citations=None, text='The file `greet.py` has been created at `/Users/yangmw/Personal/Works/Agent/greet.py` with the following content:\n\n```python\ndef greet(name):\n    """Greet a person by name."""\n    return f"Hello, {name}!"\n```\n\nThe `greet(name)` function:\n- Takes a single argument `name`\n- Returns a greeting string in the format `"Hello, {name}!"`\n- Includes a docstring describing its purpose', type='text')], model='claude-sonnet-4-6', role='assistant', stop_reason='end_turn', stop_sequence=None, type='message', usage=Usage(cache_creation=CacheCreation(ephemeral_1h_input_tokens=0, ephemeral_5m_input_tokens=0), cache_creation_input_tokens=0, cache_read_input_tokens=0, inference_geo='not_available', input_tokens=722, output_tokens=120, server_tool_use=None, service_tier='standard'), stop_details=None)

# ===== FULL MESSAGES DEBUG =====

# --- message 0 ---
# {'role': 'user', 'content': 'Create a file called greet.py with a greet(name) function'}

# --- message 1 ---
# {'role': 'assistant', 'content': [ToolUseBlock(id='toolu_01PAiYrbm874JjH7VKJAskh4', caller=DirectCaller(type='direct'), input={'command': 'cat << \'EOF\' > /Users/yangmw/Personal/Works/Agent/greet.py\ndef greet(name):\n    """Greet a person by name."""\n    return f"Hello, {name}!"\nEOF'}, name='bash', type='tool_use')]}

# --- message 2 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'toolu_01PAiYrbm874JjH7VKJAskh4', 'content': '(no output)'}]}

# --- message 3 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text='The file `greet.py` has been created at `/Users/yangmw/Personal/Works/Agent/greet.py` with the following content:\n\n```python\ndef greet(name):\n    """Greet a person by name."""\n    return f"Hello, {name}!"\n```\n\nThe `greet(name)` function:\n- Takes a single argument `name`\n- Returns a greeting string in the format `"Hello, {name}!"`\n- Includes a docstring describing its purpose', type='text')]}
# The file `greet.py` has been created at `/Users/yangmw/Personal/Works/Agent/greet.py` with the following content:

# ```python
# def greet(name):
#     """Greet a person by name."""
#     return f"Hello, {name}!"
# ```

# The `greet(name)` function:
# - Takes a single argument `name`
# - Returns a greeting string in the format `"Hello, {name}!"`
# - Includes a docstring describing its purpose

# s01 >> q
# (general) yangmw@bogon Agent % 