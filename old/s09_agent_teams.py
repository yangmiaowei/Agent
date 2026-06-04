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
class MessageBus:  # 消息总线，收/发/广播消息
    def __init__(self, inbox_dir: Path):
        self.dir = inbox_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    def send(self, sender: str, to: str, content: str,
             msg_type: str = "message", extra: dict = None) -> str:
        if msg_type not in VALID_MSG_TYPES:
            return f"Error: Invalid type '{msg_type}'. Valid: {VALID_MSG_TYPES}"
        msg = {
            "type": msg_type,
            "from": sender,
            "content": content,
            "timestamp": time.time(),
        }
        if extra:
            msg.update(extra)
        inbox_path = self.dir / f"{to}.jsonl"
        with open(inbox_path, "a") as f:
            f.write(json.dumps(msg) + "\n")
        return f"Sent {msg_type} to {to}"

    def read_inbox(self, name: str) -> list:
        inbox_path = self.dir / f"{name}.jsonl"
        if not inbox_path.exists():
            return []
        messages = []
        for line in inbox_path.read_text().strip().splitlines():  # 可以把 () 理解成：执行这个函数（方法）
            # 如果是inbox_path.read_text.strip()，相当于拿到的不是文件内容，而是 方法对象（method object）
            # x = inbox_path.read_text
            # print(type(x))
            # 输出类似：<class 'method'>
            # 然后代码继续：x.strip()
            # 但方法对象没有 strip() 方法，所以会报错：
            # AttributeError: 'method' object has no attribute 'strip'
            if line:
                messages.append(json.loads(line))
            inbox_path.write_text("")  # 清空文件内容
            return messages

    def broadcast(self, sender: str, content: str, teammates: list) -> str:
        count = 0
        for name in teammates:
            if name != sender:
                self.send(sender, name, content, "broadcast")
                count += 1
        return f"Broadcast to {count} teammates"


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
        self.config_path.write_text(json.dumps(self.config, indent=2))

    def _find_member(self, name: str) -> dict:
        for m in self.config["members"]:
            if m["name"] == name:
                return m
        return None

    def spawn(self, name: str, role: str, prompt: str) -> str:
        # 创建一个持久存在的队友（Agent），并让它在独立线程中运行
        member = self._find_member(name)
        if member:
            if member["status"] not in ("idle", "shutdown"):
                return f"Error: '{name}' is currently {member['status']}"
            member["status"] = "working"
            member["role"] = role
        else:
            member = {"name": name, "role": role, "status": "working"}
            self.config["members"].append(member)
        self._save_config()  # 更新 config
        thread = threading.Thread(  # 新建一个独立Agent开始工作
            target=self._teammate_loop,
            args=(name, role, prompt),
            daemon=True,
        )
        self.threads[name] = thread
        thread.start()
        return f"Spawned '{name}' (role: {role})"


    def _teammate_loop(self, name: str, role: str, prompt: str):
        sys_prompt = (
            f"You are '{name}', role: {role}, at {WORKDIR}."
            f"Use send_message to communicate. Complete your task."
        )
        messages = [{"role": "user", "content": prompt}]
        tools = self._teammate_tools()
        for _ in range(50):
            inbox = BUS.read_inbox(name)  # 读收件箱
            for msg in inbox:
                messages.append({"role": "user", "content": json.dumps(msg)})
            try:
                response = client.messages.create(
                    model=MODEL,
                    system=sys_prompt,
                    messages=messages,
                    tools=too,
                    max_tokens=8000,
                )  # 调用模型开始思考
            except Exception:
                break
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason != "tool_use":
                break
            results = []
            for block in response.content:
                if block.type == "tool_use":
                    output = self._exec(name, block.name, block.input)
                    print(f"  [{name}] {block.name}: {str(output)[:120]}")
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(output),
                    })
            messages.append({"role": "user", "content": results})  # Anthropic 的消息模型里只有：user assistant 两个角色
        member = self._find_member(name)
        if member and member["status"] != "shutdown":
            member["status"] = "idle"
            self._save_config()

    def _exec(self, sender: str, tool_name: str, args: dict) -> str:
        if tool_name == "bash":
            return _run_bash(args["command"])
        if tool_name == "read_file":
            return _run_read(args["path"])
        if tool_name == "write_file":
            return _run_write(args["path"], args["content"])
        if tool_name == "edit_file":
            return _run_edit(args["path"], args["old_text"], args["new_text"])
        if tool_name == "send_message":
            return BUS.send(sender, args["to"], args["content"], args.get("msg_type", "message"))
        if tool_name == "read_inbox":
            return json.dumps(BUS.read_inbox(sender), indent=2)
        return f"Unknow tool: {tool_name}"

    def _teammate_tools(self) -> list:
        return [
            {"name": "bash", "description": "Run a shell command.",
             "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
            {"name": "read_file", "description": "Read file contents.",
             "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
            {"name": "write_file", "description": "Write content to file.",
             "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
            {"name": "edit_file", "description": "Replace exact text in file.",
             "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
            {"name": "send_message", "description": "Send message to a teammate.",
             "input_schema": {"type": "object", "properties": {"to": {"type": "string"}, "content": {"type": "string"}, "msg_type": {"type": "string", "enum": list(VALID_MSG_TYPES)}, "required": ["to", "content"]}}},  # enum即只能从指定列表中选择
            {"name": "read_inbox", "description": "Read and drain your inbox.",
             "input_schema": {"type": "object", "properties": {}}},
        ]

    def list_all(self) -> str:
        if not self.config["members"]:
            return "No teammates."
        lines = [f"Team: {self.config['team_name']}"]
        for m in self.config["members"]:
            lines.append(f" {m['name']} ({m['role']}): {m['status']}")
        return "\n".join(lines)

    def member_names(self) -> list:
        return [m["name"] for m in self.config["members"]]


TEAM = TeammatedManager(TEAM_DIR)


# -- Base tool implementations --
def _safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path

def _run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"

def _run_read(path: str, limit: int = None) -> str:
    try:
        lines = _safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"

def _run_write(path: str, content: str) -> str:
    try:
        fp = _safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes"
    except Exception as e:
        return f"Error: {e}"

def _run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = _safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


TOOL_HANDLERS = {
    "bash":             lambda **kw: _run_bash(kw["command"]),
    "read_file":        lambda **kw: _run_read(kw["path"], kw.get("limit")),
    "write_file":       lambda **kw: _run_write(kw["path"], kw["content"]),
    "edit_file":        lambda **kw: _run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "spawn_teammate":   lambda **kw: TEAM.spawn(kw["name"], kw["role"], kw["prompt"]),
    "list_teamates":    lambda **kw: TEAM.list_all(),
    "send_message":     lambda **kw: BUS.send("lead", kw["to"], kw["content"], kw.get("msg_type", "message")),
    "read_inbox":       lambda **kw: json.dumps(BUS.read_inbox("lead"), indent=2),
    "broadcast":        lambda **kw: BUS.broadcast("lead", kw["content"], TEAM.member_names()),
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
    {"name": "spawn_teammate", "description": "Spawn a persistent teammate that runs in its own thread.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "role": {"type": "string"}, "prompt": {"type": "string"}}, "required": ["name", "role", "prompt"]}},
    {"name": "list_teammates", "description": "List all teammates with name, role, status.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "send_message", "description": "Send a message to a teammate's inbox.",
     "input_schema": {"type": "object", "properties": {"to": {"type": "string"}, "content": {"type": "string"}, "msg_type": {"type": "string", "enum": list(VALID_MSG_TYPES)}}, "required": ["to", "content"]}},
    {"name": "read_inbox", "description": "Read and drain the lead's inbox.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "broadcast", "description": "Send a message to all teammates.",
     "input_schema": {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]}},
]


def agent_loop(messages: list):
    while True:
        inbox = BUS.read_inbox("lead")
        if inbox:
            messages.append({
                "role": "user",
                "content": f"<inbox>{json.dumps(inbox, indent=2)}</inbox>",
            })
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

        # response_content = history[-1]["content"]
        # if isinstance(response_content, list):
        #     for block in response_content:
        #         if hasattr(block, "text"):
        #             print(block.text)
        print()


# s01 >> Spawn alice (coder) and bob (tester). Have alice send bob a message.
# > spawn_teammate:
# Spawned 'alice' (role: coder)
# > spawn_teammate:
# Spawned 'bob' (role: tester)
# > send_message:
# Sent message to alice
# > read_inbox:
# []
# > list_teammates:
# Unknown tool: list_teammates
# > list_teammates:
# Unknown tool: list_teammates

# ===== FULL MESSAGES DEBUG =====

# --- message 0 ---
# {'role': 'user', 'content': 'Spawn alice (coder) and bob (tester). Have alice send bob a message.'}

# --- message 1 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text="I'll spawn both teammates first, then have Alice send Bob a message.", type='text'), ToolUseBlock(id='call_4569b79b2fe346fd83dba362', caller=None, input={'name': 'alice', 'role': 'coder', 'prompt': 'You are Alice, a coder teammate. You write clean, efficient code. When you receive messages, respond appropriately. You can communicate with other teammates by sending messages.'}, name='spawn_teammate', type='tool_use'), ToolUseBlock(id='call_a363e274746340e1a5eaea2e', caller=None, input={'name': 'bob', 'role': 'tester', 'prompt': 'You are Bob, a tester teammate. You write thorough tests and verify code quality. When you receive messages, respond appropriately. You can communicate with other teammates by sending messages.'}, name='spawn_teammate', type='tool_use')]}

# --- message 2 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_4569b79b2fe346fd83dba362', 'content': "Spawned 'alice' (role: coder)"}, {'type': 'tool_result', 'tool_use_id': 'call_a363e274746340e1a5eaea2e', 'content': "Spawned 'bob' (role: tester)"}]}

# --- message 3 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text="Both teammates are spawned. Now I'll have Alice send a message to Bob.", type='text'), ToolUseBlock(id='call_2ec62f0a14c0496fa5d8712b', caller=None, input={'to': 'alice', 'content': "Hi Alice, please send a message to Bob introducing yourself and letting him know you're ready to collaborate."}, name='send_message', type='tool_use')]}

# --- message 4 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_2ec62f0a14c0496fa5d8712b', 'content': 'Sent message to alice'}]}

# --- message 5 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text='Let me check my inbox to see if Alice has responded, and also verify the team status.', type='text'), ToolUseBlock(id='call_59b5db62286548e1a110d293', caller=None, input={}, name='read_inbox', type='tool_use'), ToolUseBlock(id='call_c4ff6ed5c5a14938a36a8ff8', caller=None, input={}, name='list_teammates', type='tool_use')]}

# --- message 6 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_59b5db62286548e1a110d293', 'content': '[]'}, {'type': 'tool_result', 'tool_use_id': 'call_c4ff6ed5c5a14938a36a8ff8', 'content': 'Unknown tool: list_teammates'}]}

# --- message 7 ---
# {'role': 'assistant', 'content': [ToolUseBlock(id='call_eb89fa05e20542bbb78a5a83', caller=None, input={}, name='list_teammates', type='tool_use')]}

# --- message 8 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_eb89fa05e20542bbb78a5a83', 'content': 'Unknown tool: list_teammates'}]}

# --- message 9 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text="Here's a summary of what was done:\n\n1. ✅ **Spawned Alice (coder)** — She's up and running, ready to write code.\n2. ✅ **Spawned Bob (tester)** — He's up and running, ready to test.\n3. ✅ **Sent Alice a message** — I asked Alice to send Bob a message introducing herself.\n\nAlice has received the request and should be sending Bob a message shortly. The team is set up and ready to collaborate! 🚀", type='text')]}