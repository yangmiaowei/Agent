## 在当前 Agent 系统中实现任务功能

### 一、旧实现的核心功能分析

`old/s07_task_system.py` 实现了一个持久化的任务系统，核心组件包括：

**TaskManager 类：**
- 任务 CRUD 操作（创建、读取、更新、列出）
- 依赖图管理（blockedBy 字段）
- JSON 文件持久化（`.tasks/` 目录）
- 自动依赖清除（任务完成时自动移除阻塞关系）

**任务工具：**
- `task_create`: 创建新任务
- `task_update`: 更新任务状态/依赖关系
- `task_list`: 列出所有任务及状态
- `task_get`: 获取单个任务详情

**任务状态：** `pending`, `in_progress`, `completed`

---

### 二、当前 Agent 系统架构

当前系统的关键组件：

```
BaseTool (抽象基类)
    ↓
ToolManager (运行时工具管理器)
    ↓
ToolRegistry (静态工具注册表)
    ↓
BaseLoop (主执行循环)
    ↓
RuntimePolicyEngine (运行时策略引擎)
```

---

### 三、实现步骤

#### **步骤 1：创建 TaskManager 类**

在 `src/` 下创建 `src/tasks/task_manager.py`:

```python
import json
from pathlib import Path
from typing import Optional, List

class TaskManager:
    """任务管理器，支持持久化和依赖图"""

    def __init__(self, workdir: Path):
        self.workdir = workdir
        self.dir = workdir / ".tasks"
        self.dir.mkdir(exist_ok=True)
        self._next_id = self._max_id() + 1

    def _max_id(self) -> int:
        ids = [int(f.stem.split("_")[1])
               for f in self.dir.glob("task_*.json")]
        return max(ids) if ids else 0

    def _load(self, task_id: int) -> dict:
        path = self.dir / f"task_{task_id}.json"
        if not path.exists():
            raise ValueError(f"Task {task_id} not found")
        return json.loads(path.read_text())

    def _save(self, task: dict):
        path = self.dir / f"task_{task['id']}.json"
        path.write_text(json.dumps(task, indent=2, ensure_ascii=False))

    def create(self, subject: str, description: str = "") -> dict:
        task = {
            "id": self._next_id,
            "subject": subject,
            "description": description,
            "status": "pending",
            "blockedBy": [],
            "owner": "",
        }
        self._save(task)
        self._next_id += 1
        return task

    def get(self, task_id: int) -> dict:
        return self._load(task_id)

    def update(self, task_id: int, status: Optional[str] = None,
               add_blocked_by: Optional[List[int]] = None,
               remove_blocked_by: Optional[List[int]] = None) -> dict:
        task = self._load(task_id)
        if status:
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Invalid status: {status}")
            task["status"] = status
            if status == "completed":
                self._clear_dependency(task_id)
        if add_blocked_by:
            task["blockedBy"] = list(set(task["blockedBy"] + add_blocked_by))
        if remove_blocked_by:
            task["blockedBy"] = [x for x in task["blockedBy"]
                                 if x not in remove_blocked_by]
        self._save(task)
        return task

    def _clear_dependency(self, completed_id: int):
        """移除已完成任务 ID 的所有阻塞关系"""
        for f in self.dir.glob("task_*.json"):
            task = json.loads(f.read_text())
            if completed_id in task.get("blockedBy", []):
                task["blockedBy"].remove(completed_id)
                self._save(task)

    def list_all(self) -> List[dict]:
        tasks = []
        files = sorted(
            self.dir.glob("task_*.json"),
            key=lambda f: int(f.stem.split("_")[1])
        )
        for f in files:
            tasks.append(json.loads(f.read_text()))
        return tasks
```

#### **步骤 2：创建任务工具类**

在 `src/tools/` 下创建四个工具文件：

**`src/tools/task_create.py`:**

```python
from typing import Any, Dict
from src.tools.base_tool import BaseTool
from src.tasks.task_manager import TaskManager
from src.workspace import get_workdir

class TaskCreate(BaseTool):
    name = "task_create"
    description = "Create a new task for planning and tracking work."
    input_schema = {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": "Short summary of what the task is about"
            },
            "description": {
                "type": "string",
                "description": "Detailed description of the task"
            }
        },
        "required": ["subject"]
    }

    def __init__(self, task_manager: TaskManager = None):
        if task_manager:
            self._tm = task_manager
        else:
            workdir = get_workdir()
            self._tm = TaskManager(workdir)

    def run(self, subject: str, description: str = "") -> str:
        task = self._tm.create(subject, description)
        return json.dumps(task, indent=2, ensure_ascii=False)

import json
```

**`src/tools/task_update.py`:**

```python
import json
from typing import Any, Dict
from src.tools.base_tool import BaseTool
from src.tasks.task_manager import TaskManager
from src.workspace import get_workdir

class TaskUpdate(BaseTool):
    name = "task_update"
    description = "Update task status or dependencies."
    input_schema = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "ID of the task to update"
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed"],
                "description": "New status for the task"
            },
            "addBlockedBy": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Add tasks that block this task"
            },
            "removeBlockedBy": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Remove tasks that block this task"
            }
        },
        "required": ["task_id"]
    }

    def __init__(self, task_manager: TaskManager = None):
        if task_manager:
            self._tm = task_manager
        else:
            workdir = get_workdir()
            self._tm = TaskManager(workdir)

    def run(self, task_id: int, status: str = None,
            addBlockedBy: list = None, removeBlockedBy: list = None) -> str:
        task = self._tm.update(task_id, status, addBlockedBy, removeBlockedBy)
        return json.dumps(task, indent=2, ensure_ascii=False)
```

**`src/tools/task_list.py`:**

```python
from typing import Any, Dict, List
from src.tools.base_tool import BaseTool
from src.tasks.task_manager import TaskManager
from src.workspace import get_workdir

class TaskList(BaseTool):
    name = "task_list"
    description = "List all tasks with their status and dependencies."
    input_schema = {
        "type": "object",
        "properties": {}
    }

    def __init__(self, task_manager: TaskManager = None):
        if task_manager:
            self._tm = task_manager
        else:
            workdir = get_workdir()
            self._tm = TaskManager(workdir)

    def run(self) -> str:
        tasks = self._tm.list_all()
        if not tasks:
            return "No tasks."
        lines = []
        for t in tasks:
            marker = {
                "pending": "[ ]",
                "in_progress": "[>]",
                "completed": "[x]"
            }.get(t["status"], "[?]")
            blocked = f" (blocked by: {t['blockedBy']})" if t.get("blockedBy") else ""
            lines.append(f"{marker} #{t['id']}: {t['subject']}{blocked}")
        return "\n".join(lines)
```

**`src/tools/task_get.py`:**

```python
import json
from typing import Any, Dict
from src.tools.base_tool import BaseTool
from src.tasks.task_manager import TaskManager
from src.workspace import get_workdir

class TaskGet(BaseTool):
    name = "task_get"
    description = "Get full details of a task by ID."
    input_schema = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "ID of the task to retrieve"
            }
        },
        "required": ["task_id"]
    }

    def __init__(self, task_manager: TaskManager = None):
        if task_manager:
            self._tm = task_manager
        else:
            workdir = get_workdir()
            self._tm = TaskManager(workdir)

    def run(self, task_id: int) -> str:
        task = self._tm.get(task_id)
        return json.dumps(task, indent=2, ensure_ascii=False)
```

#### **步骤 3：创建 Plugin 注册任务工具**

在 `src/plugins/` 下创建 `src/plugins/tasks_plugin.py`:

```python
from src.plugins.base import Plugin
from src.registry.tool_registry import ToolRegistry
from src.tools.task_create import TaskCreate
from src.tools.task_update import TaskUpdate
from src.tools.task_list import TaskList
from src.tools.task_get import TaskGet
from src.tasks.task_manager import TaskManager

class TasksPlugin(Plugin):
    name = "tasks"

    def register(self, registry: ToolRegistry, plugin_config: dict) -> None:
        from src.workspace import get_workdir
        workdir = get_workdir()
        task_manager = TaskManager(workdir)

        # 注册共享 TaskManager 实例的工具
        tools = [
            TaskCreate(task_manager),
            TaskUpdate(task_manager),
            TaskList(task_manager),
            TaskGet(task_manager)
        ]

        for tool in tools:
            registry.add_tool_instance(tool)  # 需要在 ToolRegistry 中添加此方法
```

**注意：** 需要在 `ToolRegistry` 中添加 `add_tool_instance` 方法：

```python
# src/registry/tool_registry.py
def add_tool_instance(self, tool: BaseTool) -> BaseTool:
    """注册已经构造好的工具实例（用于需要依赖注入的场景）"""
    name = tool.name
    if name in self._tool_classes:
        raise ValueError(f"Tool conflict: {name}")
    self._tool_classes[name] = tool  # 这里可能需要改为存储实例
    return tool
```

或者更简单的做法：让每个工具类自己获取 TaskManager 的单例。

#### **步骤 4：在主程序中启用插件**

找到主程序入口（通常在 `src/` 根目录），添加 TasksPlugin：

```python
from src.plugins.tasks_plugin import TasksPlugin

# 在初始化插件列表时添加
plugins = [CoreToolsPlugin(), TasksPlugin(), ...]
```

---

### 四、集成说明

**工作流程：**

```
用户输入
    ↓
BaseLoop.loop()
    ↓
RuntimePolicyEngine.resolve() → 返回 ToolView
    ↓
Agent.run() → 返回带有 task_* 工具调用的响应
    ↓
ToolExecutor.run() → 调用对应工具
    ↓
TaskManager (持久化到 .tasks/ 目录)
    ↓
返回结果给 Agent
```

**配置选项：**

可以在 `config.yaml` 或配置字典中添加：

```yaml
plugins:
  tasks:
    enabled: true
    tasks_dir: ".tasks"  # 可选，默认 .tasks/
```

**与现有工具的关系：**

- `todo` 工具是内存中的任务列表（临时）
- `task_*` 工具是持久化的任务系统（跨会话）

两者可以共存，服务于不同的使用场景。

---

### 五、依赖图特性保持

旧实现的依赖图特性在新实现中完全保留：

```python
# 创建任务1, 2, 3
task_create(subject="Setup project")           # id=1
task_create(subject="Write code")              # id=2
task_create(subject="Write tests")             # id=3

# 设置依赖：2 依赖 1，3 依赖 2
task_update(task_id=2, addBlockedBy=[1])
task_update(task_id=3, addBlockedBy=[2])

# 完成任务1会自动解除任务2的阻塞
task_update(task_id=1, status="completed")
# → task 2 的 blockedBy 自动变为 []
```

---

### 六、注意事项

1. **线程安全**：如果需要多线程访问，需要在 TaskManager 中加锁
2. **错误处理**：工具的 `run()` 方法应捕获异常并返回友好错误信息
3. **权限控制**：在 `RuntimePolicyEngine` 中可以为任务工具添加权限策略
4. **文件清理**：可以考虑添加 `task_delete` 工具用于删除已完成任务

这样的实现完全复用了当前 agent 系统的工具架构，同时保持了旧实现的所有核心功能。