#!/usr/bin/env python3
# Harness: on-demand knowledge -- domain expertise, loaded when the model asks.
# "用到什么知识, 临时加载什么知识" -- 通过 tool_result 注入, 不塞 system prompt。
# Harness 层: 按需知识 -- 模型开口要时才给的领域专长。

# agent本质是不是functioncall?
# agent 是“以 function call 为执行接口的循环决策系统”。
# 更本质是：agent = RL-style interaction loop
"""
s05_skill_loading.py - Skills

Two-layer skill injection that avoids bloating the system prompt:

    Layer 1 (cheap): skill names in system prompt (~100 tokens/skill)
    Layer 2 (on demand): full skill body in tool_result

    skills/
      pdf/
        SKILL.md          <-- frontmatter (name, description) + body
      code-review/
        SKILL.md

    System prompt:
    +--------------------------------------+
    | You are a coding agent.              |
    | Skills available:                    |
    |   - pdf: Process PDF files...        |  <-- Layer 1: metadata only
    |   - code-review: Review code...      |
    +--------------------------------------+

    When model calls load_skill("pdf"):
    +--------------------------------------+
    | tool_result:                         |
    | <skill>                              |
    |   Full PDF processing instructions   |  <-- Layer 2: full body
    |   Step 1: ...                        |
    |   Step 2: ...                        |
    | </skill>                             |
    +--------------------------------------+

Key insight: "Don't put everything in the system prompt. Load on demand."
"""

import os
import re
import string
import subprocess
import yaml
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"), api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = os.environ["MODEL_ID"]
SKILL_DIR = WORKDIR / "skills"


# -- SkillLoader: scan skills/<name>/SKILL.md with YAML frontmatter --
class SkillLoader:
    def __init__(self, skill_dir: Path):
        self.skill_dir = skill_dir
        self.skills = {}
        self._load_all()
    
    def _load_all(self):
        if not self.skill_dir.exists():
            return
        for f in sorted(self.skill_dir.rglob("SKILL.md")):  # recursive glob 从skill_dir目录开始递归进入子目录查找文件，类似glob
            text = f.read_text()
            meta, body = self._parse_frontmatter(text)
            name = meta.get("name", f.parent.name)  # name
            # 扫描所有 SKILL.md 文件 → 读取内容 → 解析元数据 → 注册成一个 skill 字典。
            self.skills[name] = {"meta": meta, "body": body, "path": str(f)}

    def _parse_frontmatter(self, text: str) -> tuple:
        """Parse YAML frontmatter between -- delimiters."""
        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text
        try:
            meta = yaml.safe_load(match.group(1)) or {}  # load
        except yaml.YAMLError:
            meta = {}
        return meta, match.group(2).strip()

    def get_descriptions(self) -> str:
        """Layer 1: short descriptions for the system prompt."""
        if not self.skills:
            return "(no skills available)"
        lines = []
        for name, skill in self.skills.items():
            desc = skill["meta"].get("description", "No description")
            tags = skill["meta"].get("tags", "")
            line = f" - {name}: {desc}"
            if tags:
                line += f" [{tags}]"
            lines.append(line)
        return "\n".join(lines)

    def get_content(self, name: str) -> str:  # 结构化prompt
        """Layer 2: full skill body returned in tool_result."""
        skill = self.skills.get(name)
        if not skill:
            return f"Error: Unknown skill '{name}'. Available: {','.join(self.skills.keys())}"
        return f"<skill name=\"{name}\">\n{skill['body']}\n</skill>"


SKILL_LOADER = SkillLoader(SKILL_DIR)

# Layer 1: skill metadata injected into system prompt
SYSTEM = f"""You are a coding agent at {WORKDIR}. 
Use load_skill to access specialized knowledge before tackling unfamiliar topics.

Skills available:
{SKILL_LOADER.get_descriptions()}"""


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
    "load_skill": lambda **kw: SKILL_LOADER.get_content(kw["name"]),
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
    {"name": "load_skill", "description": "Load specialized knowledge by name.",
    "input_schema": {"type": "object", "properties": {"name": {"type": "string", "description": "Skill name to load"}}, "required": ["name"]}},
]


def agent_loop(messages: list):
    while True:
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
        for block in response.content:
            if block.type == "tool_use":
                handler = TOOL_HANDLERS.get(block.name)
                try:
                    output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                except Exception as e:
                    output = f"Error: {e}"
                print(f"> {block.name}:")
                print(str(output[:200]))
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


# (general) yangmw@YangdeMacBook-Air Agent % /opt/anaconda3/envs/general/bin/python /Users/yangmw/Personal/Works/Agent/s04_subagent.py
# s01 >> Use a task to create a new module, then verify it from here
# > task (Create a new module): Create a new Python module at /Users/yangmw/Personal/Works/Agent/mymodule/. The 

# ===== SUBAGENT DEBUG =====

# --- sub message 0 ---
# {'role': 'user', 'content': 'Create a new Python module at /Users/yangmw/Personal/Works/Agent/mymodule/. The module should include:\n\n1. An `__init__.py` that exports the main function.\n2. A `core.py` file with a function called `greet(name: str) -> str` that returns a greeting string like "Hello, {name}!".\n3. A `utils.py` file with a helper function `format_message(message: str) -> str` that uppercases and strips the message.\n\nMake sure the `__init__.py` properly imports and exposes `greet` from `core.py`.'}

# --- sub message 1 ---
# {'role': 'assistant', 'content': [ToolUseBlock(id='call_9e1cab133187483cb7834a75', caller=None, input={'command': 'mkdir -p /Users/yangmw/Personal/Works/Agent/mymodule'}, name='bash', type='tool_use')]}

# --- sub message 2 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_9e1cab133187483cb7834a75', 'content': '(no output)'}]}

# --- sub message 3 ---
# {'role': 'assistant', 'content': [ToolUseBlock(id='call_f25ae56a4f024ed79c9e8c9a', caller=None, input={'path': '/Users/yangmw/Personal/Works/Agent/mymodule/core.py', 'content': 'def greet(name: str) -> str:\n    """Return a greeting string for the given name."""\n    return f"Hello, {name}!"\n'}, name='write_file', type='tool_use'), ToolUseBlock(id='call_7c7f7cbaed824a54b8e2ca69', caller=None, input={'path': '/Users/yangmw/Personal/Works/Agent/mymodule/utils.py', 'content': 'def format_message(message: str) -> str:\n    """Uppercase and strip the given message."""\n    return message.strip().upper()\n'}, name='write_file', type='tool_use'), ToolUseBlock(id='call_06a8e28c6b9c4b15a508e731', caller=None, input={'path': '/Users/yangmw/Personal/Works/Agent/mymodule/__init__.py', 'content': 'from .core import greet\n\n__all__ = ["greet"]\n'}, name='write_file', type='tool_use')]}

# --- sub message 4 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_f25ae56a4f024ed79c9e8c9a', 'content': 'Wrote 113 bytes'}, {'type': 'tool_result', 'tool_use_id': 'call_7c7f7cbaed824a54b8e2ca69', 'content': 'Wrote 125 bytes'}, {'type': 'tool_result', 'tool_use_id': 'call_06a8e28c6b9c4b15a508e731', 'content': 'Wrote 45 bytes'}]}

# --- sub message 5 ---
# {'role': 'assistant', 'content': [ToolUseBlock(id='call_6690772cc2054480bd6f454a', caller=None, input={'command': 'cd /Users/yangmw/Personal/Works/Agent && python3 -c "\nfrom mymodule import greet\nfrom mymodule.utils import format_message\n\n# Test greet\nassert greet(\'World\') == \'Hello, World!\', f\'greet failed: {greet(\\"World\\")}\'\nassert greet(\'Alice\') == \'Hello, Alice!\', f\'greet failed: {greet(\\"Alice\\")}\'\n\n# Test format_message\nassert format_message(\'  hello  \') == \'HELLO\', f\'format_message failed: {format_message(\\"  hello  \\")}\'\nassert format_message(\'  Hello, World!  \') == \'HELLO, WORLD!\', f\'format_message failed: {format_message(\\"  Hello, World!  \\")}\'\n\nprint(\'All tests passed!\')\n"\n'}, name='bash', type='tool_use')]}

# --- sub message 6 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_6690772cc2054480bd6f454a', 'content': 'All tests passed!'}]}

# --- sub message 7 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text='All files have been created and verified. Here\'s a summary of what was set up:\n\n**`/Users/yangmw/Personal/Works/Agent/mymodule/`**\n\n| File | Contents |\n|---|---|\n| **`__init__.py`** | Imports `greet` from `.core` and exports it via `__all__`, so users can do `from mymodule import greet`. |\n| **`core.py`** | Defines `greet(name: str) -> str` which returns `f"Hello, {name}!"`. |\n| **`utils.py`** | Defines `format_message(message: str) -> str` which strips whitespace and uppercases the message. |\n\nAll three functions were tested and pass as expected.', type='text')]}
# All files have been created and verified. Here's a summary of what was set up:

# **`/Users/yangmw/Personal/Works/Agent/mymodule/`**

# | File | Contents |
# |---|---|
# | **`__init__.py`** | Imports `greet` 
# from .core import greet

# __all__ = ["greet"]
# def greet(name: str) -> str:
#     """Return a greeting string for the given name."""
#     return f"Hello, {name}!"
# def format_message(message: str) -> str:
#     """Uppercase and strip the given message."""
#     return message.strip().upper()
# greet("World")  -> Hello, World!
# format_message("  hello  ") -> HELLO

# All tests passed! ✅

# ===== FULL MESSAGES DEBUG =====

# --- message 0 ---
# {'role': 'user', 'content': 'Use a task to create a new module, then verify it from here'}

# --- message 1 ---
# {'role': 'assistant', 'content': [ToolUseBlock(id='call_4c7bd65ab5b64d16bc259327', caller=None, input={'description': 'Create a new module', 'prompt': 'Create a new Python module at /Users/yangmw/Personal/Works/Agent/mymodule/. The module should include:\n\n1. An `__init__.py` that exports the main function.\n2. A `core.py` file with a function called `greet(name: str) -> str` that returns a greeting string like "Hello, {name}!".\n3. A `utils.py` file with a helper function `format_message(message: str) -> str` that uppercases and strips the message.\n\nMake sure the `__init__.py` properly imports and exposes `greet` from `core.py`.'}, name='task', type='tool_use')]}

# --- message 2 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_4c7bd65ab5b64d16bc259327', 'content': 'All files have been created and verified. Here\'s a summary of what was set up:\n\n**`/Users/yangmw/Personal/Works/Agent/mymodule/`**\n\n| File | Contents |\n|---|---|\n| **`__init__.py`** | Imports `greet` from `.core` and exports it via `__all__`, so users can do `from mymodule import greet`. |\n| **`core.py`** | Defines `greet(name: str) -> str` which returns `f"Hello, {name}!"`. |\n| **`utils.py`** | Defines `format_message(message: str) -> str` which strips whitespace and uppercases the message. |\n\nAll three functions were tested and pass as expected.'}]}

# --- message 3 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text='The task completed. Now let me verify the created module from here by reading the files and running a quick test:', type='text'), ToolUseBlock(id='call_0dcac6a00cc5465eb0e5f489', caller=None, input={'path': '/Users/yangmw/Personal/Works/Agent/mymodule/__init__.py'}, name='read_file', type='tool_use'), ToolUseBlock(id='call_15c6fb267b894cb3ae198487', caller=None, input={'path': '/Users/yangmw/Personal/Works/Agent/mymodule/core.py'}, name='read_file', type='tool_use'), ToolUseBlock(id='call_a6054c8d909d4e55ba2383c4', caller=None, input={'path': '/Users/yangmw/Personal/Works/Agent/mymodule/utils.py'}, name='read_file', type='tool_use')]}

# --- message 4 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_0dcac6a00cc5465eb0e5f489', 'content': 'from .core import greet\n\n__all__ = ["greet"]'}, {'type': 'tool_result', 'tool_use_id': 'call_15c6fb267b894cb3ae198487', 'content': 'def greet(name: str) -> str:\n    """Return a greeting string for the given name."""\n    return f"Hello, {name}!"'}, {'type': 'tool_result', 'tool_use_id': 'call_a6054c8d909d4e55ba2383c4', 'content': 'def format_message(message: str) -> str:\n    """Uppercase and strip the given message."""\n    return message.strip().upper()'}]}

# --- message 5 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text='Files look good. Let me run a quick Python test to verify the module works correctly:', type='text'), ToolUseBlock(id='call_05ba6354428d4953974cd3b9', caller=None, input={'command': 'cd /Users/yangmw/Personal/Works/Agent && python3 -c "\nfrom mymodule import greet\nfrom mymodule.utils import format_message\n\n# Test greet()\nassert greet(\'World\') == \'Hello, World!\', \'greet failed\'\nprint(f\'greet(\\"World\\")  -> {greet(\\"World\\")}\')\n\n# Test format_message()\nassert format_message(\'  hello  \') == \'HELLO\', \'format_message failed\'\nprint(f\'format_message(\\"  hello  \\") -> {format_message(\\"  hello  \\")}\')\n\nprint(\'\\nAll tests passed! ✅\')\n"'}, name='bash', type='tool_use')]}

# --- message 6 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_05ba6354428d4953974cd3b9', 'content': 'greet("World")  -> Hello, World!\nformat_message("  hello  ") -> HELLO\n\nAll tests passed! ✅'}]}

# --- message 7 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text='Everything is verified and working! Here\'s a summary of what was created:\n\n| File | Purpose |\n|---|---|\n| **`mymodule/__init__.py`** | Exports `greet` from `core.py` via `__all__` |\n| **`mymodule/core.py`** | Contains `greet(name)` → returns `"Hello, {name}!"` |\n| **`mymodule/utils.py`** | Contains `format_message(msg)` → strips & uppercases the message |\n\nBoth functions were tested and pass as expected. ✅', type='text')]}

# s01 >> 