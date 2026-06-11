## 插件系统是什么

当前项目里的 **plugins** 不是运行时动态加载的扩展包，而是一套 **启动期组装机制**：在 agent 开始工作之前，按配置决定「要不要把某些能力挂到主 agent 上」。

它解决的核心问题是：

- **能力可开关**：比如 subagent 可以在配置里关掉，主 agent 就看不到 `task` 工具
- **组装与核心解耦**：`setup.py` 只负责注册基础工具 + 调用插件，具体 subagent 怎么建、建几种，由 `SubagentPlugin` 自己处理
- **可扩展**：以后新增 MCP、search 等能力，可以再加一个 `Plugin` 实现，不必继续改 `setup.py` 核心逻辑

目前只有一个插件：`SubagentPlugin`（`name = "subagent"`）。

---

## 涉及哪些文件

| 文件 | 职责 |
|------|------|
| `src/plugins/base.py` | 定义 `Plugin` 接口和 `BuildContext` 上下文 |
| `src/plugins/manager.py` | `PluginManager`：读配置、遍历插件、调用 `setup()` |
| `src/plugins/subagent_plugin.py` | 具体实现：构建各 subagent runtime，注册 `Task` 工具 |
| `src/config/loader.py` | 加载 `agent_config.json`，支持环境变量覆盖 |
| `src/config/agent_config.json` | 默认插件配置 |
| `src/setup.py` | 组装入口，在注册完 `CORE_TOOLS` 后调用 `PluginManager` |

---

## 在什么流程中起作用

**关键点：插件只在进程启动时执行一次，不在每次用户输入时执行。**

完整时序如下：

```mermaid
sequenceDiagram
    participant CLI as cli/main.py
    participant Setup as setup.build_main_runtime()
    participant Config as config/loader.py
    participant PM as PluginManager
    participant SP as SubagentPlugin
    participant TM as 主 ToolManager
    participant Loop as BaseLoop
    participant LLM as 模型
    participant Task as Task 工具
    participant Sub as SubAgentLoop

    CLI->>Setup: 模块导入时 build_main_runtime()
    Setup->>TM: 注册 CORE_TOOLS (5个基础工具)
    Setup->>PM: setup_all(main_tm)
    PM->>Config: load_config() (若未传 config)
    PM->>SP: setup(ctx, plugin_config)
    SP->>SP: load_subagent_types() + 构建各类型 runtime
    SP->>TM: register_instance(Task(...))
    Setup->>Loop: 用 main_tm 构建 BaseLoop
    Setup-->>CLI: 返回 agent_loop, logger

    Note over CLI,Sub: 以下为运行时 REPL 循环

    CLI->>Loop: loop(history, logger)
    Loop->>LLM: list_tools() 包含 task (若插件启用)
    LLM->>Loop: tool_use: task(subagent_type=read, ...)
    Loop->>Task: tools.call("task", ...)
    Task->>Sub: runtimes["read"].loop(prompt)
    Sub-->>Task: 摘要文本
    Task-->>Loop: 返回给主 agent
```

对应代码入口：

```5:5:src/cli/main.py
agent_loop, logger = build_main_runtime()
```

```26:35:src/setup.py
def build_main_runtime(config=None):
    main_tm = ToolManager()
    _register(main_tm, CORE_TOOLS)

    PluginManager(config).setup_all(main_tm)

    main_loop = _build_loop(main_tm, BaseLoop)
    ...
    return main_loop, logger
```

也就是说：

1. **导入 `cli/main.py` 时**，`build_main_runtime()` 就已经跑完了
2. **插件在这一步完成所有注册**
3. 之后 REPL 循环里，只是普通地使用已经组装好的 `BaseLoop` + `ToolManager`

---

## 各层具体做了什么

### 1. `Plugin` 接口（`base.py`）

```15:20:src/plugins/base.py
class Plugin(abc.ABC):
    name: str

    @abc.abstractmethod
    def setup(self, ctx: BuildContext, plugin_config: dict) -> None:
        pass
```

每个插件在启动时收到两样东西：

- **`BuildContext`**：共享上下文，目前包含：
  - `main_tm`：主 agent 的 `ToolManager`（插件往这里挂工具）
  - `core_tools`：基础工具类列表
  - `config`：完整配置
- **`plugin_config`**：该插件自己的配置片段，例如 `config["plugins"]["subagent"]`

插件的职责就是：**在 `setup()` 里完成自己的初始化，并向 `ctx.main_tm` 注册能力**。

---

### 2. `PluginManager`（`manager.py`）

```12:26:src/plugins/manager.py
class PluginManager:
    def __init__(self, config: dict | None = None):
        self.config = config if config is not None else load_config()

    def setup_all(self, main_tm: ToolManager) -> None:
        ctx = BuildContext(...)
        for name, plugin in PLUGINS.items():
            plugin_config = self.config.get("plugins", {}).get(name, {})
            if not plugin_config.get("enabled", True):
                continue
            plugin.setup(ctx, plugin_config)
```

它做三件事：

1. **读配置**：默认从 `agent_config.json` 读；也可用环境变量覆盖
2. **检查 `enabled`**：为 `false` 则跳过该插件，相当于这个功能从未存在
3. **依次调用各插件的 `setup()`**

当前注册表：

```7:9:src/plugins/manager.py
PLUGINS: dict[str, Plugin] = {
    "subagent": SubagentPlugin(),
}
```

---

### 3. `SubagentPlugin`（`subagent_plugin.py`）

这是目前唯一有实际行为的插件。`setup()` 流程：

```33:39:src/plugins/subagent_plugin.py
    def setup(self, ctx: BuildContext, plugin_config: dict) -> None:
        type_defs = load_subagent_types(plugin_config)
        if not type_defs:
            return

        runtimes = {t.name: _build_subagent_runtime(t) for t in type_defs}
        ctx.main_tm.register_instance(Task(runtimes, type_defs))
```

分四步：

**Step A — 解析 subagent 类型**

调用 `load_subagent_types(plugin_config)`：

- 从内置 `DEFAULT_TYPES` 拿 `read` / `shell` / `full`
- 合并配置里的 `custom_types`
- 用 `enabled_types` 过滤，只保留启用的类型

**Step B — 为每种类型构建独立 runtime**

每种类型各自有一套完整子环境：

```
SubagentTypeDef
  → ToolManager (只含该类型允许的工具)
  → AnthropicClient
  → BaseAgent
  → SubAgentLoop (带独立 system_prompt)
  → JsonLogger (日志目录: WORKDIR/SubAgent/<type_name>/)
```

例如 `read` 类型只有 `read_file`；`shell` 有 bash + 文件读写；`full` 再加 `todo`。

**Step C — 注册 `Task` 工具到主 ToolManager**

把上面所有 runtime 打包进一个 `Task` 实例：

```python
Task(runtimes={"read": (loop, logger), "shell": (...), ...}, type_defs=[...])
```

`Task` 会据此动态生成：

- `description`：列出可用 subagent 类型
- `input_schema`：`subagent_type` 的 `enum` 只包含启用的类型

**Step D — 主 agent 因此多出一个 `task` 工具**

若插件 `enabled: false`，这整步不会发生，主 agent 始终只有 5 个 core 工具。

---

## 配置如何影响插件

默认配置：

```1:9:src/config/agent_config.json
{
  "plugins": {
    "subagent": {
      "enabled": true,
      "enabled_types": ["read", "shell", "full"],
      "custom_types": {}
    }
  }
}
```

`loader.py` 还支持环境变量：

| 环境变量 | 效果 |
|----------|------|
| `SUBAGENT_ENABLED=false` | 关闭 subagent 插件，不注册 `task` |
| `SUBAGENT_TYPES=read,shell` | 只启用这两种类型，`task` 的 enum 也只剩这两个 |

配置只在 **PluginManager 初始化时** 生效，运行中改配置不会自动热更新。

---

## 插件启用后，运行时怎么走

插件本身不参与 REPL 循环，但它注册的工具会参与。

### 主 agent 看到什么

`BaseLoop` 每次调模型时，会把 `main_tm.list_tools()` 发给 API：

```12:29:src/runtime/base_loop.py
    def loop(self, messages: list, logger=None):
        while True:
            response = self.agent.run(messages, tools=self.tools)
            ...
            if block.type == "tool_use":
                output = self.tools.call(block.name, block.input)
```

若 subagent 插件启用，`list_tools()` 会包含 `task`，且 schema 里带有当前启用的 `subagent_type` 枚举。

### 模型调用 `task` 时

```54:63:src/tools/task.py
    def run(self, **kwargs) -> str:
        ...
        profile = kwargs.get("subagent_type", self._default_type)
        ...
        loop, logger = self._runtimes[profile]
        return loop.loop(prompt=kwargs["prompt"], logger=logger)
```

路由逻辑：

1. 取 `subagent_type`，默认 `full`；若 `full` 未启用则用第一个可用类型
2. 从 `self._runtimes` 取出对应 `SubAgentLoop` 和 logger
3. 子 agent 在**全新上下文**里跑，工具集受类型限制
4. 只把最终摘要文本返回给主 agent

这些 runtime 都是 **插件在启动时预建好的**；运行时 `Task.run()` 只做查表和分发。

---

## 启用 vs 关闭的对比

| 场景 | 启动时 | 主 agent 工具 | 模型能否 spawn subagent |
|------|--------|---------------|-------------------------|
| `enabled: true` | `SubagentPlugin.setup()` 执行 | 6 个（5 core + task） | 能，按 `subagent_type` 路由 |
| `enabled: false` | 插件被跳过 | 5 个（仅 core） | 不能，模型看不到 `task` |
| `enabled_types: ["read"]` | 只建 read runtime | task 的 enum 只有 `read` | 只能 spawn read 类型 |

---

## 设计边界（需要知道的限制）

1. **只在启动期起作用**：插件不负责每次对话的逻辑，只负责「把能力挂上去」
2. **不是动态热插拔**：没有 `unload()`、没有运行时开关；改配置需重启进程
3. **目前只有一个插件**：框架已抽象，但 `PLUGINS` 里只有 `subagent`
4. **自定义类型靠配置，不靠 runtime API**：新类型写在 `agent_config.json` 的 `custom_types`，启动时合并进 registry
5. **子 agent 不能再 spawn subagent**：各类型 runtime 的工具集里不含 `task`，避免递归

---

## 一句话总结

**plugins 是 agent 的「启动组装层」**：在 `build_main_runtime()` 时读配置，决定是否为 subagent 构建多套独立 runtime，并把 `task` 工具注册到主 `ToolManager`。之后 REPL 里主 agent 通过 `task` 工具把任务路由到对应类型的 `SubAgentLoop`；插件本身不再介入。

如果你希望，我可以再画一张「只关注 subagent 插件内部」的更细流程图，或者说明如何新增第二个插件（比如 search）。