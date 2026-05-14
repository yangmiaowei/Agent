#!/usr/bin/env python3
# Harness: team mailboxes -- multiple models, coordinated through files.
# "任务太大一个人干不完, 要能分给队友" -- 持久化队友 + JSONL 邮箱。
# Harness 层: 团队邮箱 -- 多个模型, 通过文件协调。

# Subagent (s04) 是一次性的: 生成、干活、返回摘要、消亡。没有身份, 没有跨调用的记忆。
# Background Tasks (s08) 能跑 shell 命令, 但做不了 LLM 引导的决策。

# 真正的团队协作需要三样东西: 
# (1) 能跨多轮对话存活的持久 Agent, 
# (2) 身份和生命周期管理, 
# (3) Agent 之间的通信通道。


# message passing vs shared memory

# # Message Passing
# * Agent间通过消息通信
# * 消息是不可变事件
# * 解耦，稳定，可恢复
# * 更适合LLM协作
# * 共享状态越多越复杂

# # Shared Memory
# * 多Agent共享同一状态
# * 易发生race condition
# * 容易上下文污染
# * 中间推理不应共享
# * 只共享稳定事实

# 混合架构
# Agent之间：发消息
# 长期知识：存vector db / postgres
# 任务状态：存task store
# 日志：append-only event log
# “共享事实” 而不是 “共享思维过程”

"""
s09_agent_teams.py - Agent Teams

Persistent named agents with file-based JSONL inboxes. Each teammate runs
its own agent loop in a separate thread. Communication via append-only inboxes.

    Subagent (s04):  spawn -> execute -> return summary -> destroyed
    Teammate (s09):  spawn -> work -> idle -> work -> ... -> shutdown

    .team/config.json                   .team/inbox/
    +----------------------------+      +------------------+
    | {"team_name": "default",   |      | alice.jsonl      |
    |  "members": [              |      | bob.jsonl        |
    |    {"name":"alice",        |      | lead.jsonl       |
    |     "role":"coder",        |      +------------------+
    |     "status":"idle"}       |
    |  ]}                        |      send_message("alice", "fix bug"):
    +----------------------------+        open("alice.jsonl", "a").write(msg)

                                        read_inbox("alice"):
    spawn_teammate("alice","coder",...)   msgs = [json.loads(l) for l in ...]
         |                                open("alice.jsonl", "w").close()
         v                                return msgs  # drain
    Thread: alice             Thread: bob
    +------------------+      +------------------+
    | agent_loop       |      | agent_loop       |
    | status: working  |      | status: idle     |
    | ... runs tools   |      | ... waits ...    |
    | status -> idle   |      |                  |
    +------------------+      +------------------+

    5 message types (all declared, not all handled here):
    +-------------------------+-----------------------------------+
    | message                 | Normal text message               |
    | broadcast               | Sent to all teammates             |
    | shutdown_request        | Request graceful shutdown (s10)   |
    | shutdown_response       | Approve/reject shutdown (s10)     |
    | plan_approval_response  | Approve/reject plan (s10)         |
    +-------------------------+-----------------------------------+

Key insight: "Teammates that can talk to each other."
"""

import json
import os
import subprocess
import threading
import time
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"), api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = os.environ["MODEL_ID"]
TEAM_DIR = WORKDIR / ".team"
INBOX_DIR = TEAM_DIR / "inbox"

SYSTEM = f"You are a team lead at {WORKDIR}. Spawn teammates and communicate via inboxes."

VALID_MSG_TYPES = {
    "message",
    "broadcast",
    "shutdown_request",
    "shutdown_response",
    "plan_approval_response",
}


# -- MessageBus: JSONL inbox per teammate --
class MessageBus:
    def __init__(self, inbox_dir: Path):
        self.dir = inbox_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    def send(self, sender: str, to: str, content: str,
             msg_type: str = "message", extra: dict = None) -> str:
        if msg_type not in VALID_MSG_TYPES:
            return f"Error: Invalid type '{msg_type}'. Valid: {VALID_MSG_TYPES}"
        pass

    def read_inbox(self, name: str) -> list:
        pass

    def broadcast(self, sender: str, content: str, teammates: list) -> str:
        pass


BUS = MessageBus(INBOX_DIR)


# -- TeammateManager: persistent named agents with config.json --
class TeammatedManager:
    def __init__(self, team_dir: Path):
        self.dir = team_dir
        self.dir.mkdir(exist_ok=True)
        self.config_path = self.dir / "config.json"
        self.config = self._load_config()
        self.threads = {}

    def _load_config(self) -> dict:
        if self.config_path.exists():
            return json.loads(self.config_path.read_text())
        return {"team_name": "default", "members": []}

    def _save_config(self):
        pass

    def _find_member(self, name: str) -> dict:
        pass

    def spawn(self, name: str, role: str, prompt: str) -> str:
        pass

    def _teammate_loop(self, name: str, role: str, prompt: str):
        pass

    def _exec(self, sender: str, tool_name: str, args: dict) -> str:
        pass

    def _teammate_tools(self) -> list:
        pass

    def list_all(self) -> str:
        pass

    def member_names(self) -> list:
        pass


TEAM = TeammatedManager(TEAM_DIR)


# -- Base tool implementations --
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
    "bash":             lambda **kw: run_bash(kw["command"]),
    "read_file":        lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file":       lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":        lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "background_run":   lambda **kw: BG.run(kw["command"]),
    "check_background": lambda **kw: BG.check(kw.get("task_id")),
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
    {"name": "background_run", "description": "Run command in background thread. Returns task_id immediately.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "check_background", "description": "Check background task status. Omit task_id to list all.",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}}}},
]


def agent_loop(messages: list):
    while True:
        # Drain background notifications and inject as system message before LLM call
        notifs = BG.drain_notifications()
        if notifs and messages:
            notif_text = "\n".join(
                f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in notifs
            )
            messages.append({"role": "user", "content": f"<background-results>\n{notif_text}\n</background-results>"})
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
                print(output[:200])
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


# s01 >> Start 3 background tasks: "sleep 2", "sleep 4", "sleep 6". Check their status.
# > background_run:
# Background task 29c425a5 started: sleep 2
# > background_run:
# Background task 38eed22c started: sleep 4
# > background_run:
# Background task 7a22178c started: sleep 6
# > check_background:
# [completed] sleep 2
# (no output)
# > check_background:
# [running] sleep 4
# (running)
# > check_background:
# [running] sleep 6
# (running)

# ===== FULL MESSAGES DEBUG =====

# --- message 0 ---
# {'role': 'user', 'content': 'Start 3 background tasks: "sleep 2", "sleep 4", "sleep 6". Check their status.'}

# --- message 1 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text="I'll start all 3 background tasks simultaneously since they're independent of each other.", type='text'), ToolUseBlock(id='call_20045b5fab6d49da941f9a5b', caller=None, input={'command': 'sleep 2'}, name='background_run', type='tool_use'), ToolUseBlock(id='call_e4d5057e33c243e9bde4a136', caller=None, input={'command': 'sleep 4'}, name='background_run', type='tool_use'), ToolUseBlock(id='call_f9a3850c53094554abbe35dd', caller=None, input={'command': 'sleep 6'}, name='background_run', type='tool_use')]}

# --- message 2 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_20045b5fab6d49da941f9a5b', 'content': 'Background task 29c425a5 started: sleep 2'}, {'type': 'tool_result', 'tool_use_id': 'call_e4d5057e33c243e9bde4a136', 'content': 'Background task 38eed22c started: sleep 4'}, {'type': 'tool_result', 'tool_use_id': 'call_f9a3850c53094554abbe35dd', 'content': 'Background task 7a22178c started: sleep 6'}]}

# --- message 3 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text='All 3 tasks are launched! Now let me check their status:', type='text'), ToolUseBlock(id='call_6664753e275341abb02a9962', caller=None, input={'task_id': '29c425a5'}, name='check_background', type='tool_use'), ToolUseBlock(id='call_7d590d0f3e43407f9e5df880', caller=None, input={'task_id': '38eed22c'}, name='check_background', type='tool_use'), ToolUseBlock(id='call_7cd25c68efec44bd91a6b7af', caller=None, input={'task_id': '7a22178c'}, name='check_background', type='tool_use')]}

# --- message 4 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_6664753e275341abb02a9962', 'content': '[completed] sleep 2\n(no output)'}, {'type': 'tool_result', 'tool_use_id': 'call_7d590d0f3e43407f9e5df880', 'content': '[running] sleep 4\n(running)'}, {'type': 'tool_result', 'tool_use_id': 'call_7cd25c68efec44bd91a6b7af', 'content': '[running] sleep 6\n(running)'}]}

# --- message 5 ---
# {'role': 'user', 'content': '<background-results>\n[bg:29c425a5] completed: (no output)\n</background-results>'}

# --- message 6 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text="Here's the current status of all 3 tasks:\n\n| Task ID | Command | Status |\n|---------|---------|--------|\n| `29c425a5` | `sleep 2` | ✅ **Completed** |\n| `38eed22c` | `sleep 4` | ⏳ **Running** |\n| `7a22178c` | `sleep 6` | ⏳ **Running** |\n\nThe `sleep 2` task has already finished (as confirmed by the background notification), while `sleep 4` and `sleep 6` are still running. They should complete at roughly the 4-second and 6-second marks respectively. Would you like me to check on them again?", type='text')]}

# s01 >> 