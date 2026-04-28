import os
import subprocess

from tools import Tools

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