#!/usr/bin/env python3
# Harness: autonomy -- models that find work without being told.

# "队友自己看看板, 有活就认领" -- 不需要领导逐个分配, 自组织。
# Harness 层: 自治 -- 模型自己找活干, 无需指派。

# 一个细节: Context Compact (s06) 后 Agent 可能忘了自己是谁。身份重注入解决这个问题。
"""
s11_autonomous_agents.py - Autonomous Agents

Idle cycle with task board polling, auto-claiming unclaimed tasks, and
identity re-injection after context compression. Builds on s10's protocols.

    Teammate lifecycle:
    +-------+
    | spawn |
    +---+---+
        |
        v
    +-------+  tool_use    +-------+
    | WORK  | <----------- |  LLM  |
    +---+---+              +-------+
        |
        | stop_reason != tool_use
        v
    +--------+
    | IDLE   | poll every 5s for up to 60s
    +---+----+
        |
        +---> check inbox -> message? -> resume WORK
        |
        +---> scan .tasks/ -> unclaimed? -> claim -> resume WORK
        |
        +---> timeout (60s) -> shutdown

    Identity re-injection after compression:
    messages = [identity_block, ...remaining...]
    "You are 'coder', role: backend, team: my-team"

Key insight: "The agent finds work itself."
"""

import json
import os
import subprocess
import threading
import time
import uuid
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
TASK_DIR = WORKDIR / ".tasks"

POLL_INTERVAL = 5
IDLE_TIMEOUT = 60

SYSTEM = f"You are a team lead at {WORKDIR}. Teammates are autonomous -- they find work themselves."

VALID_MSG_TYPES = {
    "message",
    "broadcast",
    "shutdown_request",
    "shutdown_response",
    "plan_approval_response",
}

# -- Request trackers --
shutdown_requests = {}
plan_requests = {}
_tracker_lock = threading.Lock()
_claim_lock = threading.Lock()


# -- MessageBus: JSONL inbox per teammate --
class MessageBus:
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
        for line in inbox_path.read_text().strip().splitlines():
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


# -- Task board scanning --
def scan_unclaimed_tasks() -> list:
    #  扫描所有还没人接的任务
    TASK_DIR.mkdir(exist_ok=True)
    unclaimed = []
    for f in sorted(TASK_DIR.glob("task_*.json")):
        task = json.loads(f.read_text())
        if (task.get("status") == "pending"  # 任务未开始
                and not task.get("owner")  # 无人负责
                and not task.get("blockedBy")):  # 没有依赖任务
            unclaimed.append(task)
    return unclaimed

def claim_task(task_id: int, owner: str) -> str:
    # 执行抢任务
    with _claim_lock:  # 加锁
        path = TASK_DIR / f"task_{task_id}.json"  # 找任务文件
        if not path.exists():
            return f"Error: Task {task_id} not found"
        task = json.loads(path.read_text())  # 读取
        if task.get("owner"):  # 已经有人领了
            existing_owner = task.get("owner") or "someone else"
            return f"Error: Task {task_id} has already been claimed by {existing_owner}"
        if task.get("status") != "pending":  # 检查状态
            status = task.get("status")
            return f"Error: Task {task_id} cannot be claimed because its status is '{status}'"
        if task.get("blockedBy"):  # 检查依赖
            return f"Error: Task {task_id} is blocked by other task(s) and cannot be claimed yet"
        task["owner"] = owner  # 领取
        task["status"] = "in_progress"  # 状态
        path.write_text(json.dumps(task, indent=2))  # 更新写回
    return f"Claimed task #{task_id} for {owner}"


# -- Identity re-injection after compression --
def make_identity_block(name: str, role: str, team_name: str) -> dict:
    # 身份重注入（Identity Re-injection）机制，防止压缩后模型忘记身份
    return {
        "role": "user",  # 通常不允许在对话过程中动态插入新的 system message，用 user 模拟一个高优先级提醒
        "content": f"<identity>You are '{name}', role: {role}, team: {team_name}. Continue your work.</identity>",
    }  # <identity> 标签 让模型更容易识别该信息


# -- Autonomous TeammateManager --
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

    def _set_status(self, name: str, status: str):
        member = self._find_member(name)
        if member:
            member["status"] = status
            self._save_config()

    def spawn(self, name: str, role: str, prompt: str) -> str:
        member = self._find_member(name)
        if member:
            if member["status"] not in ("idle", "shutdown"):
                return f"Error: '{name}' is currently {member['status']}"
            member["status"] = "working"
            member["role"] = role
        else:
            member = {"name": name, "role": role, "status": "working"}
            self.config["members"].append(member)
        self._save_config()
        thread = threading.Thread(
            target=self._teammate_loop,
            args=(name, role, prompt),
            daemon=True,
        )
        self.threads[name] = thread
        thread.start()
        return f"Spawned '{name}' (role: {role})"


    def _loop(self, name: str, role: str, prompt: str):
        team_name = self.config["team_name"]
        sys_prompt = (
            f"You are '{name}', role: {role}, team: {team_name}, at {WORKDIR}."
            f"Use idle tool when you have no more work. You will auto-claim new tasks."
        )
        messages = [{"role": "user", "content": prompt}]
        tools = self._teammate_tools()

        while True:
            # -- WORK PHASE: standard agent loop --
            for _ in range(50):
                inbox = BUS.read_inbox(name)
                for msg in inbox:
                    if msg.get("type") == "shutdown_request":
                        self._set_status(name, "shutdown")  # 关闭
                        return
                    messages.append({"role": "user", "content": json.dumps(msg)})
                try:
                    response = client.messages.create(
                        model=MODEL,
                        system=sys_prompt,
                        messages=messages,
                        tools=tools,
                        max_tokens=8000,
                    )
                except Exception:
                    self._set_status(name, "idle")  # 空闲
                    return
                messages.append({"role": "assistant", "content": response.content})
                if response.stop_reason != "tool_use":
                    break
                results = []
                for block in response.content:
                    if block.type == "tool_use":
                        if block.name == "idle":
                            idle_requested = True
                            output = "Entering idle phase. Will poll for new tasks."
                        else:
                            output = self._exec(name, block.name, block.input)
                        print(f"  [{name}] {block.name}: {str(output)[:120]}")
                        results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(output),
                        })
                messages.append({"role": "user", "content": results})
                if idle_requested:
                    break

            # -- IDLE PHASE: poll for inbox messages and unclaimed tasks --
            self._set_status(name, "idle")
            resume = False
            polls = IDLE_TIMEOUT // max(POLL_INTERVAL, 1)
            for _ in range(polls):
                time.sleep(POLL_INTERVAL)
                inbox = BUS.read_inbox(name=)





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

        if tool_name == "shutdown_response":
            req_id = args["request_id"]
            approve = args["approve"]
            with _tracker_lock:
                if req_id in shutdown_requests:
                    shutdown_requests[req_id]["status"] = "approved" if approve else "rejected"
            BUS.send(
                sender, "lead", args.get("reason", ""),
                "shutdown_response", {"request_id": req_id, "approve": approve},
            )
            return f"Shutdown {'approved' if approve else 'rejected'}"

            # shutdown_requests（状态机）
            # shutdown_requests = {
            #     "abc123": {
            #         "target": "coder",
            #         "status": "pending"
            #     }
            # }

        if tool_name == "plan_approval":
            plan_text = args.get("paln", "")
            req_id = str(uuid.uuid4())[:8]
            with _tracker_lock:
                plan_requests[req_id] = {"from": sender, "plan": plan_text, "status": "pending"}
            BUS.send(
                sender, "lead", plan_text, "plan_approval_response",
                {"request_id": req_id, "plan": plan_text},
            )
            return f"Plan submitted (request_id={req_id}). Waiting for lead approval."

            # plan_requests（第二个状态机）
            # plan_requests = {
            #     "c8f1a7e2": {
            #         "from": "coder",
            #         "plan": "...",
            #         "status": "pending"
            #     }
            # }

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
            {"name": "shutdown_response", "description": "Respond to a shutdown request. Approve to shut down, reject to keep working.",
             "input_schema": {"type": "object", "properties": {"request_id": {"type": "string"}, "approve": {"type": "boolean"}, "reason": {"type": "string"}}, "required": ["request_id", "approve"]}},
            {"name": "plan_approval", "description": "Submit a plan for lead approval. Provide plan text.",
             "input_schema": {"type": "object", "properties": {"plan": {"type": "string"}}, "required": ["plan"]}},
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

# -- Lead-specific protocol handlers --
def handle_shutdown_request(teammate: str) -> str:
    req_id = str(uuid.uuid4())[:8]
    with _tracker_lock:
        shutdown_requests[req_id] = {"target": teammate, "status": "pending"}
    BUS.send(
        "lead", teammate, "Please shut down gracefully.",
        "shutdown_request", {"request_id": req_id},
    )
    return f"Shutdown request {req_id} sent to '{teammate}' (status: pending)"

def handle_plan_review(request_id: str, approve: bool, feedback: str = "") -> str:
    with _tracker_lock:
        req = plan_requests.get(request_id)
    if not req:
        return f"Error: Unknown plan request_id '{request_id}'"
    with _tracker_lock:
        req["status"] = "approved" if approve else "rejected"
    BUS.send(
        "lead", req["from"], feedback, "plan_approval_response",
        {"request_id": request_id, "approve": approve, "feedback": feedback},
    )
    return f"Plan {req['status']} for '{req['from']}'"

def _check_shutdown_status(request_id: str) -> str:
    with _tracker_lock:
        return json.dumps(shutdown_requests.get(request_id, {"error": "not found"}))


# -- Lead tool dispatch (12 tools) --
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
    "shutdown_request":  lambda **kw: handle_shutdown_request(kw["teammate"]),
    "shutdown_response": lambda **kw: _check_shutdown_status(kw.get("request_id", "")),
    "plan_approval":     lambda **kw: handle_plan_review(kw["request_id"], kw["approve"], kw.get("feedback", "")),
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
     {"name": "shutdown_request", "description": "Request a teammate to shut down gracefully. Returns a request_id for tracking.",
     "input_schema": {"type": "object", "properties": {"teammate": {"type": "string"}}, "required": ["teammate"]}},
    {"name": "shutdown_response", "description": "Check the status of a shutdown request by request_id.",
     "input_schema": {"type": "object", "properties": {"request_id": {"type": "string"}}, "required": ["request_id"]}},
    {"name": "plan_approval", "description": "Approve or reject a teammate's plan. Provide request_id + approve + optional feedback.",
     "input_schema": {"type": "object", "properties": {"request_id": {"type": "string"}, "approve": {"type": "boolean"}, "feedback": {"type": "string"}}, "required": ["request_id", "approve"]}},
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

# s01 >> Spawn alice as a coder. Then request her shutdown.
# > spawn_teammate:
# Spawned 'alice' (role: coder)
# > shutdown_request:
# Shutdown request 71a8424c sent to 'alice' (status: pending)

# ===== FULL MESSAGES DEBUG =====

# --- message 0 ---
# {'role': 'user', 'content': 'Spawn alice as a coder. Then request her shutdown.'}

# --- message 1 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text="I'll spawn alice as a coder and then immediately request her shutdown.", type='text'), ToolUseBlock(id='call_c4eecdb0168e49a1a8d8d7f5', caller=None, input={'name': 'alice', 'role': 'coder', 'prompt': 'You are a coder teammate named alice. Follow instructions from the lead.'}, name='spawn_teammate', type='tool_use')]}

# --- message 2 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_c4eecdb0168e49a1a8d8d7f5', 'content': "Spawned 'alice' (role: coder)"}]}

# --- message 3 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text='Alice has been spawned. Now let me request her shutdown.', type='text'), ToolUseBlock(id='call_3387fb41ae69442586825253', caller=None, input={'teammate': 'alice'}, name='shutdown_request', type='tool_use')]}

# --- message 4 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_3387fb41ae69442586825253', 'content': "Shutdown request 71a8424c sent to 'alice' (status: pending)"}]}

# --- message 5 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text="Here's a summary of what happened:\n\n1. **Spawned alice** as a coder — she's now active.\n2. **Sent a shutdown request** to alice (request ID: `71a8424c`) — currently pending.\n\nAlice should acknowledge the shutdown request and wind down. Let me know if you'd like me to check the status of the shutdown or take any further action!", type='text')]}

# s01 >> List teammates to see alice's status after shutdown approval
# > list_teammates:
# Unknown tool: list_teammates
# > shutdown_response:
# {"target": "alice", "status": "pending"}

# ===== FULL MESSAGES DEBUG =====

# --- message 0 ---
# {'role': 'user', 'content': 'Spawn alice as a coder. Then request her shutdown.'}

# --- message 1 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text="I'll spawn alice as a coder and then immediately request her shutdown.", type='text'), ToolUseBlock(id='call_c4eecdb0168e49a1a8d8d7f5', caller=None, input={'name': 'alice', 'role': 'coder', 'prompt': 'You are a coder teammate named alice. Follow instructions from the lead.'}, name='spawn_teammate', type='tool_use')]}

# --- message 2 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_c4eecdb0168e49a1a8d8d7f5', 'content': "Spawned 'alice' (role: coder)"}]}

# --- message 3 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text='Alice has been spawned. Now let me request her shutdown.', type='text'), ToolUseBlock(id='call_3387fb41ae69442586825253', caller=None, input={'teammate': 'alice'}, name='shutdown_request', type='tool_use')]}

# --- message 4 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_3387fb41ae69442586825253', 'content': "Shutdown request 71a8424c sent to 'alice' (status: pending)"}]}

# --- message 5 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text="Here's a summary of what happened:\n\n1. **Spawned alice** as a coder — she's now active.\n2. **Sent a shutdown request** to alice (request ID: `71a8424c`) — currently pending.\n\nAlice should acknowledge the shutdown request and wind down. Let me know if you'd like me to check the status of the shutdown or take any further action!", type='text')]}

# --- message 6 ---
# {'role': 'user', 'content': "List teammates to see alice's status after shutdown approval"}

# --- message 7 ---
# {'role': 'assistant', 'content': [ToolUseBlock(id='call_4c9de743a3164730aa2d3e2c', caller=None, input={}, name='list_teammates', type='tool_use')]}

# --- message 8 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_4c9de743a3164730aa2d3e2c', 'content': 'Unknown tool: list_teammates'}]}

# --- message 9 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text='Let me check the shutdown status using the request ID:', type='text'), ToolUseBlock(id='call_aa3ed5b3cc07438cb7f9a9d2', caller=None, input={'request_id': '71a8424c'}, name='shutdown_response', type='tool_use')]}

# --- message 10 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_aa3ed5b3cc07438cb7f9a9d2', 'content': '{"target": "alice", "status": "pending"}'}]}

# --- message 11 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text="Alice's shutdown is still **pending** — she hasn't responded yet. It seems she may need more time to acknowledge the shutdown request. Would you like me to:\n\n1. **Wait and check again** for her shutdown response?\n2. **Send her a message** reminding her to approve the shutdown?", type='text')]}

# s01 >> 