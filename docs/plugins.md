# Agent 运行时架构

四层分工，边界严格：

```
Plugin Layer          →  能力定义（静态 register）
Runtime Layer         →  能力选择（动态 resolve）
Orchestrator Layer    →  决策循环（轻量 loop）
Execution Layer       →  执行隔离（run）
```

链路：

```
ToolRegistry (static)
    ↓
RuntimePolicyEngine (filtering + skill injection)
    ↓
BaseLoop (orchestrator)
    ↓
ToolExecutor / SubagentExecutor
```

---

## 四条铁律

| 铁律 | 规则 |
|------|------|
| 谁决定可见能力？ | **只有 Runtime** |
| 谁决定是否进 subagent？ | **LLM**（通过 `task`），但 Runtime 决定 `task` 是否可见 |
| Plugin 碰不碰运行时？ | **永远不碰**（不 build loop / agent / client） |
| Orchestrator 聪不聪明？ | **不聪明**（不做权限、不做策略） |

---

## 目录结构

| 目录 | 职责 |
|------|------|
| `src/registry/` | `ToolRegistry` 静态目录；`SubagentTypeDef` 类型声明 |
| `src/plugins/` | 插件只 `register(registry)` |
| `src/runtime/` | `RuntimeContext`、`ToolView`、`RuntimePolicyEngine`、`SkillLoader` |
| `src/orchestrator/` | `BaseLoop` 纯循环 |
| `src/execution/` | `ToolExecutor`、`SubagentExecutor`、`SubagentFactory` |
| `src/setup.py` | bootstrap 接线，不含业务逻辑 |

---

## 启动流程

```mermaid
sequenceDiagram
    participant CLI as cli/main.py
    participant Setup as setup.build_main_runtime()
    participant PM as PluginManager
    participant Reg as ToolRegistry
    participant RT as RuntimePolicyEngine
    participant Loop as BaseLoop
    participant LLM as 模型
    participant Exec as ToolExecutor
    participant Sub as SubagentExecutor

    CLI->>Setup: build_main_runtime()
    Setup->>PM: register_all(registry)
    PM->>Reg: CoreTools / Skills / Subagent 声明
    Setup->>RT: 创建 PolicyEngine + executor_tm
    Setup->>Loop: agent + runtime + executor
    Setup-->>CLI: loop, logger

    Note over CLI,Sub: REPL 每轮

    CLI->>Loop: loop(messages)
    Loop->>RT: resolve(ctx)
    RT-->>Loop: ToolView + system_prompt
    Loop->>LLM: chat(tool_view)
    LLM->>Loop: tool_use
    Loop->>Exec: run(name, args, tool_view)
    alt task
        Exec->>Sub: lazy build + cache + SubAgentLoop
    else 普通工具
        Exec->>Exec: ToolManager.call
    end
```

入口：

```python
# cli/main.py
agent_loop, logger = build_main_runtime()
```

---

## Plugin 层

### 接口

```python
class Plugin(abc.ABC):
    name: str

    def register(self, registry: ToolRegistry, plugin_config: dict) -> None:
        ...
```

Plugin **只做声明**：`registry.add_tool(cls)` 或 `registry.add_subagent_type(def)`。

### 当前插件

| 插件 | 注册内容 |
|------|----------|
| `CoreToolsPlugin` | bash, read_file, edit_file, write_file, todo |
| `SkillsPlugin` | load_skill |
| `SubagentPlugin` | subagent 类型声明（read / shell / full） |

SubagentPlugin **不再**构建 `SubAgentLoop`；执行由 `SubagentExecutor` 懒加载 + cache。

### 如何加新工具

1. 实现 `BaseTool` 子类
2. 新建 `Plugin.register()` 里 `registry.add_tool(...)`
3. 不改 Orchestrator / Execution

---

## Runtime 层

`RuntimePolicyEngine.resolve(ctx)` 每轮返回：

- `ToolView`：本轮 LLM 可见工具子集
- `system_prompt`：含 skill 元数据（Layer 1）

### 裁剪规则

| 条件 | 效果 |
|------|------|
| 默认 | core + load_skill + task |
| `runtime.safe_mode: true` 或 `ctx.mode="safe"` | 隐藏 bash/edit_file/write_file；task 仅 read |
| `runtime.skills_enabled: false` | 隐藏 load_skill |
| `plugins.subagent.enabled: false` | 不注册 subagent 类型；无 task |

### Skill 注入

- **Layer 1**：`SkillLoader.get_descriptions()` → system prompt
- **Layer 2**：模型调 `load_skill` → `tool_result` 注入正文

### 如何加新决策逻辑

只改 `src/runtime/resolver.py`（如 research 模式、低成本模式）。

---

## Orchestrator 层

`BaseLoop` 每轮：

1. `resolved = runtime.resolve(ctx)`
2. `agent.run(messages, tools=resolved.tool_view, system=resolved.system_prompt)`
3. `executor.run(name, args, ctx, resolved.tool_view)` — 含可见性校验

---

## Execution 层

| 组件 | 职责 |
|------|------|
| `ToolExecutor` | 校验 `tool_view.can_call()`，分发普通工具 / task |
| `SubagentExecutor` | 按 `subagent_type` 懒加载 SubAgentLoop（cache） |
| `SubagentFactory` | 为类型构建隔离 ToolManager + SubAgentLoop |

Subagent **不做策略**，只做上下文隔离与工具裁剪。

---

## 配置

`agent_config.json`：

```json
{
  "runtime": {
    "mode": "default",
    "safe_mode": false,
    "skills_enabled": true
  },
  "plugins": {
    "subagent": {
      "enabled": true,
      "enabled_types": ["read", "shell", "full"],
      "custom_types": {}
    }
  }
}
```

环境变量（`config/loader.py`）：

| 变量 | 效果 |
|------|------|
| `AGENT_MODE` | 设置 mode |
| `SAFE_MODE=true` | 安全模式 |
| `SKILLS_ENABLED=false` | 关闭 skill |
| `SUBAGENT_ENABLED=false` | 关闭 subagent 类型注册 |
| `SUBAGENT_TYPES=read,shell` | 限制 subagent 类型 |

---

## 扩展插槽速查

| 需求 | 改哪里 |
|------|--------|
| 新工具 | Plugin |
| 新 skill | `skills/*/SKILL.md` + Runtime resolver |
| 新 subagent 类型 | `registry/subagent_types.py` + config |
| 新模式 / 权限 | `runtime/resolver.py` |

---

## 设计边界

1. 配置只在启动时加载；运行中改配置需重启
2. 子 agent 不能再 spawn subagent（工具集不含 task）
3. 旧的 `PolicyLoop` 已移除；循环内策略扩展点应在 `RuntimePolicyEngine`
