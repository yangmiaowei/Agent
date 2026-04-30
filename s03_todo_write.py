#!/usr/bin/env python3
# Harness: planning -- keeping the model on course without scripting the route.
# 让模型保持在正确的轨道上，而不是事先把路线脚本化。
"""
s03_todo_write.py - TodoWrite

The model tracks its own progress via a TodoManager. A nag reminder
forces it to keep updating when it forgets.

    +----------+      +-------+      +---------+
    |   User   | ---> |  LLM  | ---> | Tools   |
    |  prompt  |      |       |      | + todo  |
    +----------+      +---+---+      +----+----+
                          ^               |
                          |   tool_result |
                          +---------------+
                                |
                    +-----------+-----------+
                    | TodoManager state     |
                    | [ ] task A            |
                    | [>] task B <- doing   |
                    | [x] task C            |
                    +-----------------------+
                                |
                    if rounds_since_todo >= 3:
                      inject <reminder>

Key insight: "The agent can track its own progress -- and I can see it."
"""

import os
import subprocess
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"), api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = os.environ["MODEL_ID"]

SYSTEM = f"""You are a coding agent at {WORKDIR}.
Use the todo tool to plan multi-step tasks. Mark in_progress before starting, completed when done.
Prefer tools over prose."""


# -- TodoManager: structured state the LLM writes to --
# 由大模型写入的结构化状态
class TodoManager:
    def __init__(self):
        self.items = []

    def update(self, items: list) -> str:
        pass

    def render(self) -> str:
        pass












# -- Tool implementations --
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


def run_read(path: str, limit: int = None) -> str:
    try:
        text = safe_path(path).read_text()  # 文件内容一次性读成一个字符串
        lines = text.splitlines()  # 按换行符拆分字符串，返回一个按行分割的列表
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"
# 这几个tool返回都是str，是因为模型只接受str吗 不是 是简化
# 精确结构（很重要） 比如： AST 表格数据 JSON API 响应 代码分析结果 ❗让模型做“程序级推理” 比如： 多步骤规划 状态机 structured tool chaining 这时候才应该： 👉 返回 JSON / dict，而不是纯字符串
# 上述简化成输入llm的是有结构的json？可是这最终不也是转成str加入模型上下文？还是模型内部怎么处理这个json数组结构？
# 是的，最终都会变成字符串（token序列）进入模型
# 但“结构化 JSON”的意义不在于内部存储，而在于token组织方式 + schema约束 + 语义分隔
def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"      

# -- The dispatch map: {tool_name: handler} --

# 把“带关键字参数的函数调用”包装成一个统一的处理入口
# lambda **kw：接收任意数量的关键字参数，并把它们打包成一个字典 kw
# kw["command"]：从参数字典里取出 "command"，只把它传给 run_bash

# TOOL_HANDLERS = {
#     "bash": lambda **kw: run_bash(kw["command"]),
# }
# 等价于：
# def bash_handler(**kw):
#     return run_bash(kw["command"])
# 只是写成了匿名函数版本 + 字典映射

# 典型的 工具分发器 / strategy pattern（策略模式）简化版
# 它的作用：用字符串选择函数：TOOL_HANDLERS["bash"]
# 所有工具统一调用方式：handler(**tool_args)

# lambda **kw: run_bash(kw["command"])
# “接收一堆参数 → 从里面挑 command → 调 run_bash”
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"])
}

TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command.",
        "input_schema": {
            "type": "object",
            "properties": {  # 定义有哪些参数
                "command": {"type": "string"}  # command 必须是字符串
            },
            "required": ["command"]
        }
    },
    {
        "name": "read_file",
        "description": "Read file contents.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "limit":{"type": "integer"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file", 
        "description": "Write content to file.",
        "input_schema": {
            "type": "object", 
            "properties": {
                "path": {"type": "string"}, 
                "content": {"type": "string"}
            }, 
            "required": ["path", "content"]
        }
    },
    {
        "name": "edit_file", 
        "description": "Replace exact text in file.",
        "input_schema": {
            "type": "object", 
            "properties": {
                "path": {"type": "string"}, 
                "old_text": {"type": "string"}, 
                "new_text": {"type": "string"}
            }, 
            "required": ["path", "old_text", "new_text"]
        }
    }
]


# -- The core pattern: a while loop that calls tools until the model stops --
def agent_loop(messages: list):
    while True:
        print("call llm:")
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000
        )
        print(response)
        # Append assistant turn
        messages.append({"role": "assistant", "content": response.content})
        # If the model didn't call a tool, we're done
        if response.stop_reason != "tool_use":
            return
        # Execute each tool call, collect results
        results = []
        for block in response.content:
            if block.type == "tool_use":
                # print(f"\033[33m$ {block.input['command']}\033[0m")
                # output = run_bash(block.input["command"])
                # print(output[:200])
                # results.append({
                #     "type": "tool_result",
                #     "tool_use_id": block.id,
                #     "content": output
                # })
                handler = TOOL_HANDLERS.get(block.name)
                output = handler(**block.input) if handler else f"Unknown tool: {block.name}"  # **的作用是把字典“解包成关键字参数”
                # print(f"> {block.name}:")
                # print(output[:200])
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
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

        # response_content = history[-1]["content"]
        # if isinstance(response_content, list):
        #     for block in response_content:
        #         if hasattr(block, "text"):
        #             print(block.text)
        print()
