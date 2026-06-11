#!/usr/bin/env python3
# Harness: persistent tasks -- goals that outlive any single conversation.
# "大目标要拆成小任务, 排好序, 记在磁盘上" -- 文件持久化的任务图, 为多 agent 协作打基础。
# Harness 层: 持久化任务 -- 比任何一次对话都长命的目标。
"""
s07_task_system.py - Tasks

Tasks persist as JSON files in .tasks/ so they survive context compression.
Each task has a dependency graph (blockedBy).

    .tasks/
      task_1.json  {"id":1, "subject":"...", "status":"completed", ...}
      task_2.json  {"id":2, "blockedBy":[1], "status":"pending", ...}
      task_3.json  {"id":3, "blockedBy":[2], ...}

    Dependency resolution:
    +----------+     +----------+     +----------+
    | task 1   | --> | task 2   | --> | task 3   |
    | complete |     | blocked  |     | blocked  |
    +----------+     +----------+     +----------+
         |                ^
         +--- completing task 1 removes it from task 2's blockedBy

Key insight: "State that survives compression -- because it's outside the conversation."
"""

import json
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
TASK_DIR = WORKDIR / ".tasks"

SYSTEM = f"You are a coding agent at {WORKDIR}. Use task tools to plan and track work."


# -- TaskManager: CRUD with dependency graph, persisted as JSON files --
class TaskManager:
    def __init__(self, tasks_dir: Path):
        self.dir = tasks_dir
        self.dir.mkdir(exist_ok=True)
        self._next_id = self._max_id() + 1

    def _max_id(self) -> int:
        ids = [int(f.stem.split("_")[1]) for f in self.dir.glob("task_*.json")]
        return max(ids) if ids else 0

    def _load(self, task_id: int) -> dict:
        path = self.dir / f"task_{task_id}.json"
        if not path.exists():
            raise ValueError(f"Task {task_id} not found")
        return json.loads(path.read_text())

    def _save(self, task: dict):
        path = self.dir / f"task_{task['id']}.json"
        path.write_text(json.dumps(task, indent=2, ensure_ascii=False))

    def create(self, subject: str, description: str = "") -> str:
        task = {
            "id": self._next_id, "subject": subject, "description": description,
            "status": "pending", "blockedBy": [], "owner": "",
        }
        self._save(task)
        self._next_id += 1
        return json.dumps(task, indent=2, ensure_ascii=False)

    def get(self, task_id: int) -> str:
        return json.dumps(self._load(task_id), indent=2, ensure_ascii=False)

    def update(self, task_id: int, status: str = None,
               add_blocked_by: list = None, remove_blocked_by: list = None) -> str:
        task = self._load(task_id)
        if status:
            if status not in ("pending", "inprogress", "completed"):
                raise ValueError(f"Invalid status: {status}")
            task["status"] = status
            if status == "completed":
                self._clear_dependency(task_id)
        if add_blocked_by:
            task["blockedBy"] = list(set(task["blockedBy"] + add_blocked_by))
        if remove_blocked_by:
            task["blockedBy"] = [x for x in task["blockedBy"] if x not in remove_blocked_by]
        self._save(task)
        return json.dumps(task, indent=2, ensure_ascii=False)

    def _clear_dependency(self, completed_id: int):
        """Remove completed_id from all other tasks' blockedBy lists."""
        for f in self.dir.glob("task_*.json"):
            task = json.loads(f.read_text())
            if completed_id in task.get("blockedBy", []):
                task["blockedBy"].remove(completed_id)
                self._save(task)

    def list_all(self) -> str:
        tasks = []
        files = sorted(
            self.dir.glob("task_*.json"),
            key=lambda f: int(f.stem.split("_")[1])  # 从文件名里提取数字作为排序依据
        )
        for f in files:
            tasks.append(json.loads(f.read_text()))
        if not tasks:
            return "No tasks."
        lines = []
        for t in tasks:
            marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}.get(t["status"], "[?]")
            blocked = f" (blocked by: {t['blockedBy']})" if t.get("blockedBy") else ""
            lines.append(f"{marker} #{t['id']}: {t['subject']}{blocked}")
        return "\n".join(lines)


TASKS = TaskManager(TASK_DIR)


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
    "bash":        lambda **kw: run_bash(kw["command"]),
    "read_file":   lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file":  lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":   lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "task_create": lambda **kw: TASKS.create(kw["subject"], kw.get("description", "")),
    "task_update": lambda **kw: TASKS.update(kw["task_id"], kw.get("status"), kw.get("addBlockedBy"), kw.get("removeBlockBy")),
    "task_list":   lambda **kw: TASKS.list_all(),
    "task_get":    lambda **kw: TASKS.get(kw["task_id"]),
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
    {"name": "task_create", "description": "Create a new task.",
     "input_schema": {"type": "object", "properties": {"subject": {"type": "string"}, "description": {"type": "string"}}, "required": ["subject"]}},
    {"name": "task_update", "description": "Update a task's status or dependencies.",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}, "addBlockedBy": {"type": "array", "items": {"type": "integer"}}, "removeBlockedBy": {"type": "array", "items": {"type": "integer"}}}, "required": ["task_id"]}},
    {"name": "task_list", "description": "List all tasks with status summary.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "task_get", "description": "Get full details of a task by ID.",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
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


# s01 >> Create 3 tasks: "Setup project", "Write code", "Write tests". Make them depend on each other in order.
# > task_create:
# {
#   "id": 1,
#   "subject": "Setup project",
#   "description": "Initialize the project structure and configuration",
#   "status": "pending",
#   "blockedBy": [],
#   "owner": ""
# }
# > task_create:
# {
#   "id": 2,
#   "subject": "Write code",
#   "description": "Implement the core functionality",
#   "status": "pending",
#   "blockedBy": [],
#   "owner": ""
# }
# > task_create:
# {
#   "id": 3,
#   "subject": "Write tests",
#   "description": "Write tests to verify the implementation",
#   "status": "pending",
#   "blockedBy": [],
#   "owner": ""
# }
# > task_update:
# {
#   "id": 2,
#   "subject": "Write code",
#   "description": "Implement the core functionality",
#   "status": "pending",
#   "blockedBy": [
#     1
#   ],
#   "owner": ""
# }
# > task_update:
# {
#   "id": 3,
#   "subject": "Write tests",
#   "description": "Write tests to verify the implementation",
#   "status": "pending",
#   "blockedBy": [
#     2
#   ],
#   "owner": ""
# }

# ===== FULL MESSAGES DEBUG =====

# --- message 0 ---
# {'role': 'user', 'content': 'Create 3 tasks: "Setup project", "Write code", "Write tests". Make them depend on each other in order.'}

# --- message 1 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text="I'll create the three tasks first, then set up the dependencies between them.", type='text'), ToolUseBlock(id='call_5c9ac160d67043f09b9f2ab9', caller=None, input={'subject': 'Setup project', 'description': 'Initialize the project structure and configuration'}, name='task_create', type='tool_use'), ToolUseBlock(id='call_abb4ac60643a41439edd0605', caller=None, input={'subject': 'Write code', 'description': 'Implement the core functionality'}, name='task_create', type='tool_use'), ToolUseBlock(id='call_cec09a796b044a15931dde6c', caller=None, input={'subject': 'Write tests', 'description': 'Write tests to verify the implementation'}, name='task_create', type='tool_use')]}

# --- message 2 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_5c9ac160d67043f09b9f2ab9', 'content': '{\n  "id": 1,\n  "subject": "Setup project",\n  "description": "Initialize the project structure and configuration",\n  "status": "pending",\n  "blockedBy": [],\n  "owner": ""\n}'}, {'type': 'tool_result', 'tool_use_id': 'call_abb4ac60643a41439edd0605', 'content': '{\n  "id": 2,\n  "subject": "Write code",\n  "description": "Implement the core functionality",\n  "status": "pending",\n  "blockedBy": [],\n  "owner": ""\n}'}, {'type': 'tool_result', 'tool_use_id': 'call_cec09a796b044a15931dde6c', 'content': '{\n  "id": 3,\n  "subject": "Write tests",\n  "description": "Write tests to verify the implementation",\n  "status": "pending",\n  "blockedBy": [],\n  "owner": ""\n}'}]}

# --- message 3 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text='Tasks created! Now let me set up the sequential dependencies:', type='text'), ToolUseBlock(id='call_4d5aba20de9d4b11b7550bbd', caller=None, input={'task_id': 2, 'addBlockedBy': [1]}, name='task_update', type='tool_use'), ToolUseBlock(id='call_81f75b67fe564c51b436462c', caller=None, input={'task_id': 3, 'addBlockedBy': [2]}, name='task_update', type='tool_use')]}

# --- message 4 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_4d5aba20de9d4b11b7550bbd', 'content': '{\n  "id": 2,\n  "subject": "Write code",\n  "description": "Implement the core functionality",\n  "status": "pending",\n  "blockedBy": [\n    1\n  ],\n  "owner": ""\n}'}, {'type': 'tool_result', 'tool_use_id': 'call_81f75b67fe564c51b436462c', 'content': '{\n  "id": 3,\n  "subject": "Write tests",\n  "description": "Write tests to verify the implementation",\n  "status": "pending",\n  "blockedBy": [\n    2\n  ],\n  "owner": ""\n}'}]}

# --- message 5 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text='All done! Here\'s a summary of the tasks and their dependency chain:\n\n| # | Task | Blocked By |\n|---|------|------------|\n| 1 | **Setup project** | — (no blockers, ready to start) |\n| 2 | **Write code** | Task 1 (Setup project) |\n| 3 | **Write tests** | Task 2 (Write code) |\n\nThe dependency flow is: **Setup project → Write code → Write tests**. Only "Setup project" can be started right now; the other two will become unblocked as their predecessors are completed.', type='text')]}

# s01 >> List all tasks and show the dependency graph
# > task_list:
# [ ] #1: Setup project
# [ ] #2: Write code (blocked by: [1])
# [ ] #3: Write tests (blocked by: [2])

# ===== FULL MESSAGES DEBUG =====

# --- message 0 ---
# {'role': 'user', 'content': 'Create 3 tasks: "Setup project", "Write code", "Write tests". Make them depend on each other in order.'}

# --- message 1 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text="I'll create the three tasks first, then set up the dependencies between them.", type='text'), ToolUseBlock(id='call_5c9ac160d67043f09b9f2ab9', caller=None, input={'subject': 'Setup project', 'description': 'Initialize the project structure and configuration'}, name='task_create', type='tool_use'), ToolUseBlock(id='call_abb4ac60643a41439edd0605', caller=None, input={'subject': 'Write code', 'description': 'Implement the core functionality'}, name='task_create', type='tool_use'), ToolUseBlock(id='call_cec09a796b044a15931dde6c', caller=None, input={'subject': 'Write tests', 'description': 'Write tests to verify the implementation'}, name='task_create', type='tool_use')]}

# --- message 2 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_5c9ac160d67043f09b9f2ab9', 'content': '{\n  "id": 1,\n  "subject": "Setup project",\n  "description": "Initialize the project structure and configuration",\n  "status": "pending",\n  "blockedBy": [],\n  "owner": ""\n}'}, {'type': 'tool_result', 'tool_use_id': 'call_abb4ac60643a41439edd0605', 'content': '{\n  "id": 2,\n  "subject": "Write code",\n  "description": "Implement the core functionality",\n  "status": "pending",\n  "blockedBy": [],\n  "owner": ""\n}'}, {'type': 'tool_result', 'tool_use_id': 'call_cec09a796b044a15931dde6c', 'content': '{\n  "id": 3,\n  "subject": "Write tests",\n  "description": "Write tests to verify the implementation",\n  "status": "pending",\n  "blockedBy": [],\n  "owner": ""\n}'}]}

# --- message 3 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text='Tasks created! Now let me set up the sequential dependencies:', type='text'), ToolUseBlock(id='call_4d5aba20de9d4b11b7550bbd', caller=None, input={'task_id': 2, 'addBlockedBy': [1]}, name='task_update', type='tool_use'), ToolUseBlock(id='call_81f75b67fe564c51b436462c', caller=None, input={'task_id': 3, 'addBlockedBy': [2]}, name='task_update', type='tool_use')]}

# --- message 4 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_4d5aba20de9d4b11b7550bbd', 'content': '{\n  "id": 2,\n  "subject": "Write code",\n  "description": "Implement the core functionality",\n  "status": "pending",\n  "blockedBy": [\n    1\n  ],\n  "owner": ""\n}'}, {'type': 'tool_result', 'tool_use_id': 'call_81f75b67fe564c51b436462c', 'content': '{\n  "id": 3,\n  "subject": "Write tests",\n  "description": "Write tests to verify the implementation",\n  "status": "pending",\n  "blockedBy": [\n    2\n  ],\n  "owner": ""\n}'}]}

# --- message 5 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text='All done! Here\'s a summary of the tasks and their dependency chain:\n\n| # | Task | Blocked By |\n|---|------|------------|\n| 1 | **Setup project** | — (no blockers, ready to start) |\n| 2 | **Write code** | Task 1 (Setup project) |\n| 3 | **Write tests** | Task 2 (Write code) |\n\nThe dependency flow is: **Setup project → Write code → Write tests**. Only "Setup project" can be started right now; the other two will become unblocked as their predecessors are completed.', type='text')]}

# --- message 6 ---
# {'role': 'user', 'content': 'List all tasks and show the dependency graph'}

# --- message 7 ---
# {'role': 'assistant', 'content': [ToolUseBlock(id='call_bf602337f4bd41e99651e688', caller=None, input={}, name='task_list', type='tool_use')]}

# --- message 8 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_bf602337f4bd41e99651e688', 'content': '[ ] #1: Setup project\n[ ] #2: Write code (blocked by: [1])\n[ ] #3: Write tests (blocked by: [2])'}]}

# --- message 9 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text="Here's the full task list and dependency graph:\n\n### Task List\n\n| # | Status | Task | Blocked By |\n|---|--------|------|------------|\n| 1 | ⬜ Pending | Setup project | — |\n| 2 | ⬜ Pending | Write code | Task 1 |\n| 3 | ⬜ Pending | Write tests | Task 2 |\n\n### Dependency Graph\n\n```\n┌─────────────────┐\n│  #1 Setup project│──────►┌─────────────────┐\n│    (no blockers) │       │  #2 Write code   │──────►┌──────────────────┐\n└─────────────────┘       │  (blocked by #1) │       │  #3 Write tests   │\n                          └─────────────────┘       │  (blocked by #2)  │\n                                                    └──────────────────┘\n```\n\n**Flow:** `Setup project` → `Write code` → `Write tests`\n\n- **Task 1** is the only one ready to start (no blockers).\n- **Task 2** will unlock once Task 1 is completed.\n- **Task 3** will unlock once Task 2 is completed.", type='text')]}

# s01 >> Complete task 1 and then list tasks to see task 2 unblocked
# > task_update:
# {
#   "id": 1,
#   "subject": "Setup project",
#   "description": "Initialize the project structure and configuration",
#   "status": "completed",
#   "blockedBy": [],
#   "owner": ""
# }
# > task_list:
# [x] #1: Setup project
# [ ] #2: Write code
# [ ] #3: Write tests (blocked by: [2])

# ===== FULL MESSAGES DEBUG =====

# --- message 0 ---
# {'role': 'user', 'content': 'Create 3 tasks: "Setup project", "Write code", "Write tests". Make them depend on each other in order.'}

# --- message 1 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text="I'll create the three tasks first, then set up the dependencies between them.", type='text'), ToolUseBlock(id='call_5c9ac160d67043f09b9f2ab9', caller=None, input={'subject': 'Setup project', 'description': 'Initialize the project structure and configuration'}, name='task_create', type='tool_use'), ToolUseBlock(id='call_abb4ac60643a41439edd0605', caller=None, input={'subject': 'Write code', 'description': 'Implement the core functionality'}, name='task_create', type='tool_use'), ToolUseBlock(id='call_cec09a796b044a15931dde6c', caller=None, input={'subject': 'Write tests', 'description': 'Write tests to verify the implementation'}, name='task_create', type='tool_use')]}

# --- message 2 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_5c9ac160d67043f09b9f2ab9', 'content': '{\n  "id": 1,\n  "subject": "Setup project",\n  "description": "Initialize the project structure and configuration",\n  "status": "pending",\n  "blockedBy": [],\n  "owner": ""\n}'}, {'type': 'tool_result', 'tool_use_id': 'call_abb4ac60643a41439edd0605', 'content': '{\n  "id": 2,\n  "subject": "Write code",\n  "description": "Implement the core functionality",\n  "status": "pending",\n  "blockedBy": [],\n  "owner": ""\n}'}, {'type': 'tool_result', 'tool_use_id': 'call_cec09a796b044a15931dde6c', 'content': '{\n  "id": 3,\n  "subject": "Write tests",\n  "description": "Write tests to verify the implementation",\n  "status": "pending",\n  "blockedBy": [],\n  "owner": ""\n}'}]}

# --- message 3 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text='Tasks created! Now let me set up the sequential dependencies:', type='text'), ToolUseBlock(id='call_4d5aba20de9d4b11b7550bbd', caller=None, input={'task_id': 2, 'addBlockedBy': [1]}, name='task_update', type='tool_use'), ToolUseBlock(id='call_81f75b67fe564c51b436462c', caller=None, input={'task_id': 3, 'addBlockedBy': [2]}, name='task_update', type='tool_use')]}

# --- message 4 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_4d5aba20de9d4b11b7550bbd', 'content': '{\n  "id": 2,\n  "subject": "Write code",\n  "description": "Implement the core functionality",\n  "status": "pending",\n  "blockedBy": [\n    1\n  ],\n  "owner": ""\n}'}, {'type': 'tool_result', 'tool_use_id': 'call_81f75b67fe564c51b436462c', 'content': '{\n  "id": 3,\n  "subject": "Write tests",\n  "description": "Write tests to verify the implementation",\n  "status": "pending",\n  "blockedBy": [\n    2\n  ],\n  "owner": ""\n}'}]}

# --- message 5 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text='All done! Here\'s a summary of the tasks and their dependency chain:\n\n| # | Task | Blocked By |\n|---|------|------------|\n| 1 | **Setup project** | — (no blockers, ready to start) |\n| 2 | **Write code** | Task 1 (Setup project) |\n| 3 | **Write tests** | Task 2 (Write code) |\n\nThe dependency flow is: **Setup project → Write code → Write tests**. Only "Setup project" can be started right now; the other two will become unblocked as their predecessors are completed.', type='text')]}

# --- message 6 ---
# {'role': 'user', 'content': 'List all tasks and show the dependency graph'}

# --- message 7 ---
# {'role': 'assistant', 'content': [ToolUseBlock(id='call_bf602337f4bd41e99651e688', caller=None, input={}, name='task_list', type='tool_use')]}

# --- message 8 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_bf602337f4bd41e99651e688', 'content': '[ ] #1: Setup project\n[ ] #2: Write code (blocked by: [1])\n[ ] #3: Write tests (blocked by: [2])'}]}

# --- message 9 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text="Here's the full task list and dependency graph:\n\n### Task List\n\n| # | Status | Task | Blocked By |\n|---|--------|------|------------|\n| 1 | ⬜ Pending | Setup project | — |\n| 2 | ⬜ Pending | Write code | Task 1 |\n| 3 | ⬜ Pending | Write tests | Task 2 |\n\n### Dependency Graph\n\n```\n┌─────────────────┐\n│  #1 Setup project│──────►┌─────────────────┐\n│    (no blockers) │       │  #2 Write code   │──────►┌──────────────────┐\n└─────────────────┘       │  (blocked by #1) │       │  #3 Write tests   │\n                          └─────────────────┘       │  (blocked by #2)  │\n                                                    └──────────────────┘\n```\n\n**Flow:** `Setup project` → `Write code` → `Write tests`\n\n- **Task 1** is the only one ready to start (no blockers).\n- **Task 2** will unlock once Task 1 is completed.\n- **Task 3** will unlock once Task 2 is completed.", type='text')]}

# --- message 10 ---
# {'role': 'user', 'content': 'Complete task 1 and then list tasks to see task 2 unblocked'}

# --- message 11 ---
# {'role': 'assistant', 'content': [ToolUseBlock(id='call_395ca7e9b43b41a48bee5b24', caller=None, input={'task_id': 1, 'status': 'completed'}, name='task_update', type='tool_use')]}

# --- message 12 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_395ca7e9b43b41a48bee5b24', 'content': '{\n  "id": 1,\n  "subject": "Setup project",\n  "description": "Initialize the project structure and configuration",\n  "status": "completed",\n  "blockedBy": [],\n  "owner": ""\n}'}]}

# --- message 13 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text='Task 1 is now completed. Let me list all tasks to confirm Task 2 is unblocked:', type='text'), ToolUseBlock(id='call_ddf32c27798e4c4999c01a1c', caller=None, input={}, name='task_list', type='tool_use')]}

# --- message 14 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_ddf32c27798e4c4999c01a1c', 'content': '[x] #1: Setup project\n[ ] #2: Write code\n[ ] #3: Write tests (blocked by: [2])'}]}

# --- message 15 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text="Here's the updated status:\n\n| # | Status | Task | Note |\n|---|--------|------|------|\n| 1 | ✅ Completed | Setup project | Done! |\n| 2 | ⬜ Pending | Write code | **Unblocked!** Ready to start 🚀 |\n| 3 | ⬜ Pending | Write tests | Still blocked by Task 2 |\n\nAs expected, completing **Task 1 (Setup project)** has unblocked **Task 2 (Write code)**, which is now ready to be picked up. Task 3 remains blocked until Task 2 is completed.", type='text')]}

# s01 >> Create a task board for refactoring: parse -> transform -> emit -> test, where transform and emit can run in parallel after parse
# > task_create:
# {
#   "id": 4,
#   "subject": "Parse",
#   "description": "Implement the parsing step — extract and structure input data",
#   "status": "pending",
#   "blockedBy": [],
#   "owner": ""
# }
# > task_create:
# {
#   "id": 5,
#   "subject": "Transform",
#   "description": "Implement the transformation step — modify/reshape the parsed data",
#   "status": "pending",
#   "blockedBy": [],
#   "owner": ""
# }
# > task_create:
# {
#   "id": 6,
#   "subject": "Emit",
#   "description": "Implement the emit step — output the transformed data in the target format",
#   "status": "pending",
#   "blockedBy": [],
#   "owner": ""
# }
# > task_create:
# {
#   "id": 7,
#   "subject": "Test",
#   "description": "Test the full parse → transform → emit pipeline end-to-end",
#   "status": "pending",
#   "blockedBy": [],
#   "owner": ""
# }
# > task_update:
# {
#   "id": 5,
#   "subject": "Transform",
#   "description": "Implement the transformation step — modify/reshape the parsed data",
#   "status": "pending",
#   "blockedBy": [
#     4
#   ],
#   "owner": ""
# }
# > task_update:
# {
#   "id": 6,
#   "subject": "Emit",
#   "description": "Implement the emit step — output the transformed data in the target format",
#   "status": "pending",
#   "blockedBy": [
#     4
#   ],
#   "owner": ""
# }
# > task_update:
# {
#   "id": 7,
#   "subject": "Test",
#   "description": "Test the full parse → transform → emit pipeline end-to-end",
#   "status": "pending",
#   "blockedBy": [
#     5,
#     6
#   ],
#   "owner": ""
# }
# > task_list:
# [x] #1: Setup project
# [ ] #2: Write code
# [ ] #3: Write tests (blocked by: [2])
# [ ] #4: Parse
# [ ] #5: Transform (blocked by: [4])
# [ ] #6: Emit (blocked by: [4])
# [ ] #7: Test (blocked by: [5, 6])

# ===== FULL MESSAGES DEBUG =====

# --- message 0 ---
# {'role': 'user', 'content': 'Create 3 tasks: "Setup project", "Write code", "Write tests". Make them depend on each other in order.'}

# --- message 1 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text="I'll create the three tasks first, then set up the dependencies between them.", type='text'), ToolUseBlock(id='call_5c9ac160d67043f09b9f2ab9', caller=None, input={'subject': 'Setup project', 'description': 'Initialize the project structure and configuration'}, name='task_create', type='tool_use'), ToolUseBlock(id='call_abb4ac60643a41439edd0605', caller=None, input={'subject': 'Write code', 'description': 'Implement the core functionality'}, name='task_create', type='tool_use'), ToolUseBlock(id='call_cec09a796b044a15931dde6c', caller=None, input={'subject': 'Write tests', 'description': 'Write tests to verify the implementation'}, name='task_create', type='tool_use')]}

# --- message 2 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_5c9ac160d67043f09b9f2ab9', 'content': '{\n  "id": 1,\n  "subject": "Setup project",\n  "description": "Initialize the project structure and configuration",\n  "status": "pending",\n  "blockedBy": [],\n  "owner": ""\n}'}, {'type': 'tool_result', 'tool_use_id': 'call_abb4ac60643a41439edd0605', 'content': '{\n  "id": 2,\n  "subject": "Write code",\n  "description": "Implement the core functionality",\n  "status": "pending",\n  "blockedBy": [],\n  "owner": ""\n}'}, {'type': 'tool_result', 'tool_use_id': 'call_cec09a796b044a15931dde6c', 'content': '{\n  "id": 3,\n  "subject": "Write tests",\n  "description": "Write tests to verify the implementation",\n  "status": "pending",\n  "blockedBy": [],\n  "owner": ""\n}'}]}

# --- message 3 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text='Tasks created! Now let me set up the sequential dependencies:', type='text'), ToolUseBlock(id='call_4d5aba20de9d4b11b7550bbd', caller=None, input={'task_id': 2, 'addBlockedBy': [1]}, name='task_update', type='tool_use'), ToolUseBlock(id='call_81f75b67fe564c51b436462c', caller=None, input={'task_id': 3, 'addBlockedBy': [2]}, name='task_update', type='tool_use')]}

# --- message 4 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_4d5aba20de9d4b11b7550bbd', 'content': '{\n  "id": 2,\n  "subject": "Write code",\n  "description": "Implement the core functionality",\n  "status": "pending",\n  "blockedBy": [\n    1\n  ],\n  "owner": ""\n}'}, {'type': 'tool_result', 'tool_use_id': 'call_81f75b67fe564c51b436462c', 'content': '{\n  "id": 3,\n  "subject": "Write tests",\n  "description": "Write tests to verify the implementation",\n  "status": "pending",\n  "blockedBy": [\n    2\n  ],\n  "owner": ""\n}'}]}

# --- message 5 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text='All done! Here\'s a summary of the tasks and their dependency chain:\n\n| # | Task | Blocked By |\n|---|------|------------|\n| 1 | **Setup project** | — (no blockers, ready to start) |\n| 2 | **Write code** | Task 1 (Setup project) |\n| 3 | **Write tests** | Task 2 (Write code) |\n\nThe dependency flow is: **Setup project → Write code → Write tests**. Only "Setup project" can be started right now; the other two will become unblocked as their predecessors are completed.', type='text')]}

# --- message 6 ---
# {'role': 'user', 'content': 'List all tasks and show the dependency graph'}

# --- message 7 ---
# {'role': 'assistant', 'content': [ToolUseBlock(id='call_bf602337f4bd41e99651e688', caller=None, input={}, name='task_list', type='tool_use')]}

# --- message 8 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_bf602337f4bd41e99651e688', 'content': '[ ] #1: Setup project\n[ ] #2: Write code (blocked by: [1])\n[ ] #3: Write tests (blocked by: [2])'}]}

# --- message 9 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text="Here's the full task list and dependency graph:\n\n### Task List\n\n| # | Status | Task | Blocked By |\n|---|--------|------|------------|\n| 1 | ⬜ Pending | Setup project | — |\n| 2 | ⬜ Pending | Write code | Task 1 |\n| 3 | ⬜ Pending | Write tests | Task 2 |\n\n### Dependency Graph\n\n```\n┌─────────────────┐\n│  #1 Setup project│──────►┌─────────────────┐\n│    (no blockers) │       │  #2 Write code   │──────►┌──────────────────┐\n└─────────────────┘       │  (blocked by #1) │       │  #3 Write tests   │\n                          └─────────────────┘       │  (blocked by #2)  │\n                                                    └──────────────────┘\n```\n\n**Flow:** `Setup project` → `Write code` → `Write tests`\n\n- **Task 1** is the only one ready to start (no blockers).\n- **Task 2** will unlock once Task 1 is completed.\n- **Task 3** will unlock once Task 2 is completed.", type='text')]}

# --- message 10 ---
# {'role': 'user', 'content': 'Complete task 1 and then list tasks to see task 2 unblocked'}

# --- message 11 ---
# {'role': 'assistant', 'content': [ToolUseBlock(id='call_395ca7e9b43b41a48bee5b24', caller=None, input={'task_id': 1, 'status': 'completed'}, name='task_update', type='tool_use')]}

# --- message 12 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_395ca7e9b43b41a48bee5b24', 'content': '{\n  "id": 1,\n  "subject": "Setup project",\n  "description": "Initialize the project structure and configuration",\n  "status": "completed",\n  "blockedBy": [],\n  "owner": ""\n}'}]}

# --- message 13 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text='Task 1 is now completed. Let me list all tasks to confirm Task 2 is unblocked:', type='text'), ToolUseBlock(id='call_ddf32c27798e4c4999c01a1c', caller=None, input={}, name='task_list', type='tool_use')]}

# --- message 14 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_ddf32c27798e4c4999c01a1c', 'content': '[x] #1: Setup project\n[ ] #2: Write code\n[ ] #3: Write tests (blocked by: [2])'}]}

# --- message 15 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text="Here's the updated status:\n\n| # | Status | Task | Note |\n|---|--------|------|------|\n| 1 | ✅ Completed | Setup project | Done! |\n| 2 | ⬜ Pending | Write code | **Unblocked!** Ready to start 🚀 |\n| 3 | ⬜ Pending | Write tests | Still blocked by Task 2 |\n\nAs expected, completing **Task 1 (Setup project)** has unblocked **Task 2 (Write code)**, which is now ready to be picked up. Task 3 remains blocked until Task 2 is completed.", type='text')]}

# --- message 16 ---
# {'role': 'user', 'content': 'Create a task board for refactoring: parse -> transform -> emit -> test, where transform and emit can run in parallel after parse'}

# --- message 17 ---
# {'role': 'assistant', 'content': [ToolUseBlock(id='call_4e303efbb7cd47d98b2c7994', caller=None, input={'subject': 'Parse', 'description': 'Implement the parsing step — extract and structure input data'}, name='task_create', type='tool_use'), ToolUseBlock(id='call_817e42274601426d99e5f19c', caller=None, input={'subject': 'Transform', 'description': 'Implement the transformation step — modify/reshape the parsed data'}, name='task_create', type='tool_use'), ToolUseBlock(id='call_daddaf3d36d44057bd35f1ec', caller=None, input={'subject': 'Emit', 'description': 'Implement the emit step — output the transformed data in the target format'}, name='task_create', type='tool_use'), ToolUseBlock(id='call_5983c78d662142d7a103300a', caller=None, input={'subject': 'Test', 'description': 'Test the full parse → transform → emit pipeline end-to-end'}, name='task_create', type='tool_use')]}

# --- message 18 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_4e303efbb7cd47d98b2c7994', 'content': '{\n  "id": 4,\n  "subject": "Parse",\n  "description": "Implement the parsing step — extract and structure input data",\n  "status": "pending",\n  "blockedBy": [],\n  "owner": ""\n}'}, {'type': 'tool_result', 'tool_use_id': 'call_817e42274601426d99e5f19c', 'content': '{\n  "id": 5,\n  "subject": "Transform",\n  "description": "Implement the transformation step — modify/reshape the parsed data",\n  "status": "pending",\n  "blockedBy": [],\n  "owner": ""\n}'}, {'type': 'tool_result', 'tool_use_id': 'call_daddaf3d36d44057bd35f1ec', 'content': '{\n  "id": 6,\n  "subject": "Emit",\n  "description": "Implement the emit step — output the transformed data in the target format",\n  "status": "pending",\n  "blockedBy": [],\n  "owner": ""\n}'}, {'type': 'tool_result', 'tool_use_id': 'call_5983c78d662142d7a103300a', 'content': '{\n  "id": 7,\n  "subject": "Test",\n  "description": "Test the full parse → transform → emit pipeline end-to-end",\n  "status": "pending",\n  "blockedBy": [],\n  "owner": ""\n}'}]}

# --- message 19 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text='Tasks created! Now let me set up the dependencies:', type='text'), ToolUseBlock(id='call_1662a88a725f4e94b7d316de', caller=None, input={'addBlockedBy': [4], 'task_id': 5}, name='task_update', type='tool_use'), ToolUseBlock(id='call_efe50535881745f1bd2be030', caller=None, input={'addBlockedBy': [4], 'task_id': 6}, name='task_update', type='tool_use'), ToolUseBlock(id='call_fb50e7ad1c754582a2545992', caller=None, input={'addBlockedBy': [5, 6], 'task_id': 7}, name='task_update', type='tool_use')]}

# --- message 20 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_1662a88a725f4e94b7d316de', 'content': '{\n  "id": 5,\n  "subject": "Transform",\n  "description": "Implement the transformation step — modify/reshape the parsed data",\n  "status": "pending",\n  "blockedBy": [\n    4\n  ],\n  "owner": ""\n}'}, {'type': 'tool_result', 'tool_use_id': 'call_efe50535881745f1bd2be030', 'content': '{\n  "id": 6,\n  "subject": "Emit",\n  "description": "Implement the emit step — output the transformed data in the target format",\n  "status": "pending",\n  "blockedBy": [\n    4\n  ],\n  "owner": ""\n}'}, {'type': 'tool_result', 'tool_use_id': 'call_fb50e7ad1c754582a2545992', 'content': '{\n  "id": 7,\n  "subject": "Test",\n  "description": "Test the full parse → transform → emit pipeline end-to-end",\n  "status": "pending",\n  "blockedBy": [\n    5,\n    6\n  ],\n  "owner": ""\n}'}]}

# --- message 21 ---
# {'role': 'assistant', 'content': [ToolUseBlock(id='call_e30b744bb1de4d45950d3720', caller=None, input={}, name='task_list', type='tool_use')]}

# --- message 22 ---
# {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_e30b744bb1de4d45950d3720', 'content': '[x] #1: Setup project\n[ ] #2: Write code\n[ ] #3: Write tests (blocked by: [2])\n[ ] #4: Parse\n[ ] #5: Transform (blocked by: [4])\n[ ] #6: Emit (blocked by: [4])\n[ ] #7: Test (blocked by: [5, 6])'}]}

# --- message 23 ---
# {'role': 'assistant', 'content': [TextBlock(citations=None, text="Here's the refactoring task board with the dependency graph:\n\n### Task Board\n\n| # | Status | Task | Blocked By |\n|---|--------|------|------------|\n| 4 | ⬜ Pending | Parse | — |\n| 5 | ⬜ Pending | Transform | #4 (Parse) |\n| 6 | ⬜ Pending | Emit | #4 (Parse) |\n| 7 | ⬜ Pending | Test | #5, #6 (Transform, Emit) |\n\n### Dependency Graph\n\n```\n                    ┌──────────────────┐\n                    │   #4 Parse        │\n                    │   (no blockers)   │\n                    └────────┬─────────┘\n                             │\n                    ┌────────┴─────────┐\n                    ▼                  ▼\n        ┌──────────────────┐  ┌──────────────────┐\n        │  #5 Transform    │  │    #6 Emit        │\n        │ (blocked by #4)  │  │ (blocked by #4)   │\n        └────────┬─────────┘  └────────┬──────────┘\n                 │                     │\n                 └──────────┬──────────┘\n                            ▼\n                ┌──────────────────┐\n                │    #7 Test        │\n                │ (blocked by #5,#6)│\n                └──────────────────┘\n```\n\n**Execution flow:**\n1. 🟢 **Parse** — ready to start now (no blockers)\n2. ⚡ **Transform** & **Emit** — both unblock in parallel once Parse is done\n3. 🔒 **Test** — unblocks only after *both* Transform and Emit are completed", type='text')]}
