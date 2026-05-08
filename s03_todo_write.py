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
        if len(items) > 20:
            raise ValueError("Max 20 todos allowed")
        validated = []
        in_progress_count = 0
        for i, item in enumerate(items):
            text = str(item.get("text", "")).strip()
            status = str(item.get("status", "pending")).lower()
            item_id = str(item.get("id", str(i + 1)))
            if not text:
                raise ValueError(f"Item {item_id}: text required")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {item_id}: invalid status '{status}'")
            if status == "in_progress":
                in_progress_count += 1
            validated.append({
                "id": item_id,
                "text": text,
                "status": status
            })
        if in_progress_count > 1:
            raise ValueError("Only one task can be in_progress at a time")
        self.items = validated
        return self.render()   

    def render(self) -> str:
        if not self.items:
            return "No todos."
        lines = []
        for item in self.items:
            marker = {
                "pending": "[ ]",
                "in_progress": "[>]",
                "completed": "[x]"
            }[item["status"]]
            lines.append(f"{marker} #{item['id']}: {item['text']}")
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)


TODO = TodoManager()


# -- Tool implementations --
def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path

def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"

def run_read(path: str, limit: int = None) -> str:
    try:
        lines = safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"

def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes"
    except Exception as e:
        return f"Error: {e}"

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


TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "todo":       lambda **kw: TODO.update(kw["items"]),
}

TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "todo", "description": "Update task list. Track progress on multi-step tasks.",
     "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}, "text": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}}, "required": ["id", "text", "status"]}}}, "required": ["items"]}},
]


# -- Agent loop with nag reminder injection --
def agent_loop(messages: list):
    rounds_since_todo = 0
    while True:
        # Nag reminder is injected below, alongside tool results
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
        results = []
        use_todo = False
        for block in response.content:
            if block.type == "tool_use":
                handler = TOOL_HANDLERS.get(block.name)
                try:
                    output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                except Exception as e:
                    output = f"Error: {e}"
                print(f"> {block.name}:")
                print(output[:200])
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
                if block.name == "todo":
                    use_todo = True
        rounds_since_todo = 0 if use_todo else rounds_since_todo + 1
        if rounds_since_todo >= 3:
            results.append({"type": "text", "text": "<reminder>Update your todos.</reminder>"})
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


# (general) yangmw@YangdeMacBook-Air Agent % /opt/anaconda3/envs/general/bin/python /Users/yangmw/Personal/Works/Agent/s03_todo_write.py
# s01 >> Refactor the file greet.py,: add type hints, docstrings, and a main guard
# > read_file:
# def greet(name):
#     """Greet a person by name."""
#     return f"Hello, {name}!"
# > todo:
# [ ] #1: Add type hints to greet function
# [ ] #2: Expand docstring to follow conventions
# [ ] #3: Add __main__ guard with example usage

# (0/3 completed)
# > todo:
# [>] #1: Add type hints to greet function
# [ ] #2: Expand docstring to follow conventions
# [ ] #3: Add __main__ guard with example usage

# (0/3 completed)
# > write_file:
# Wrote 306 bytes
# > todo:
# [x] #1: Add type hints to greet function
# [x] #2: Expand docstring to follow conventions
# [x] #3: Add __main__ guard with example usage

# (3/3 completed)
# > read_file:
# def greet(name: str) -> str:
#     """Return a greeting message for the given name.

#     Args:
#         name: The name of the person to greet.

#     Returns:
#         A greeting string in the form ``"Hello
# > bash:
# Hello, World!

# ===== FULL MESSAGES DEBUG =====

# --- message 0 ---
# {'role': 'user', 'content': 'Refactor the file greet.py,: add type hints, docstrings, and a main guard'}

# --- message 1 ---
# {'role': 'assistant', 'content': [ToolUseBlock(id='call_e8bd2781bc3a43f19a73c50b', caller=None, input={'path': '/Users/yangmw/Personal/Works/Agent/greet.py'}, name='read_file', type='tool_use')]}

# --- message 2 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_e8bd2781bc3a43f19a73c50b', 'content': 'def greet(name):\n    """Greet a person by name."""\n    return f"Hello, {name}!"'}]}

# --- message 3 ---
# {'role': 'assistant', 'content': [ToolUseBlock(id='call_b28c10c8e8d94d59bc559fc3', caller=None, input={'items': [{'id': '1', 'text': 'Add type hints to greet function', 'status': 'pending'}, {'id': '2', 'text': 'Expand docstring to follow conventions', 'status': 'pending'}, {'id': '3', 'text': 'Add __main__ guard with example usage', 'status': 'pending'}]}, name='todo', type='tool_use')]}

# --- message 4 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_b28c10c8e8d94d59bc559fc3', 'content': '[ ] #1: Add type hints to greet function\n[ ] #2: Expand docstring to follow conventions\n[ ] #3: Add __main__ guard with example usage\n\n(0/3 completed)'}]}

# --- message 5 ---
# {'role': 'assistant', 'content': [ToolUseBlock(id='call_d39d8ddae6274be1bdb318ce', caller=None, input={'items': [{'id': '1', 'status': 'in_progress', 'text': 'Add type hints to greet function'}, {'id': '2', 'status': 'pending', 'text': 'Expand docstring to follow conventions'}, {'id': '3', 'status': 'pending', 'text': 'Add __main__ guard with example usage'}]}, name='todo', type='tool_use')]}

# --- message 6 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_d39d8ddae6274be1bdb318ce', 'content': '[>] #1: Add type hints to greet function\n[ ] #2: Expand docstring to follow conventions\n[ ] #3: Add __main__ guard with example usage\n\n(0/3 completed)'}]}

# --- message 7 ---
# {'role': 'assistant', 'content': [ToolUseBlock(id='call_7d48df9605844f7aa410e028', caller=None, input={'path': '/Users/yangmw/Personal/Works/Agent/greet.py', 'content': 'def greet(name: str) -> str:\n    """Return a greeting message for the given name.\n\n    Args:\n        name: The name of the person to greet.\n\n    Returns:\n        A greeting string in the form ``"Hello, {name}!"``.\n    """\n    return f"Hello, {name}!"\n\n\nif __name__ == "__main__":\n    print(greet("World"))\n'}, name='write_file', type='tool_use')]}

# --- message 8 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_7d48df9605844f7aa410e028', 'content': 'Wrote 306 bytes'}]}

# --- message 9 ---
# {'role': 'assistant', 'content': [ToolUseBlock(id='call_353c6c7ddd30406895fcd5d3', caller=None, input={'items': [{'id': '1', 'status': 'completed', 'text': 'Add type hints to greet function'}, {'id': '2', 'status': 'completed', 'text': 'Expand docstring to follow conventions'}, {'id': '3', 'status': 'completed', 'text': 'Add __main__ guard with example usage'}]}, name='todo', type='tool_use')]}

# --- message 10 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_353c6c7ddd30406895fcd5d3', 'content': '[x] #1: Add type hints to greet function\n[x] #2: Expand docstring to follow conventions\n[x] #3: Add __main__ guard with example usage\n\n(3/3 completed)'}]}

# --- message 11 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text='Let me verify the final result:', type='text'), ToolUseBlock(id='call_81196519fd464ea79068e4ab', caller=None, input={'path': '/Users/yangmw/Personal/Works/Agent/greet.py'}, name='read_file', type='tool_use'), ToolUseBlock(id='call_0d080b8ce35d43d9a79c3f8d', caller=None, input={'command': 'cd /Users/yangmw/Personal/Works/Agent && python greet.py'}, name='bash', type='tool_use')]}

# --- message 12 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_81196519fd464ea79068e4ab', 'content': 'def greet(name: str) -> str:\n    """Return a greeting message for the given name.\n\n    Args:\n        name: The name of the person to greet.\n\n    Returns:\n        A greeting string in the form ``"Hello, {name}!"``.\n    """\n    return f"Hello, {name}!"\n\n\nif __name__ == "__main__":\n    print(greet("World"))'}, {'type': 'tool_result', 'tool_use_id': 'call_0d080b8ce35d43d9a79c3f8d', 'content': 'Hello, World!'}]}

# --- message 13 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text='All three changes are applied and working. Here\'s a summary of the refactoring:\n\n| Change | Before | After |\n|---|---|---|\n| **Type hints** | `def greet(name):` | `def greet(name: str) -> str:` |\n| **Docstring** | Single-line summary | Google-style with `Args` and `Returns` sections |\n| **Main guard** | None | `if __name__ == "__main__":` block that prints `greet("World")` |', type='text')]}

# s01 >> 