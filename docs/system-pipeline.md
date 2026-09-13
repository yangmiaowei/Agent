# Agent 系统流水线设计

## 系统流水线图

```
┌──────────────────────────────────────────────────────────────────────┐
│                         CLI Layer                                      │
│                    (cli/main.py)                                      │
│                  用户交互 → 消息收集                                   │
└──────────────────────────────────────────────────────────────────────┘
                                    ↓
┌──────────────────────────────────────────────────────────────────────┐
│                    Setup/Bootstrap                                    │
│                 (setup.build_main_runtime)                            │
│  PluginManager → ToolRegistry → RuntimePolicyEngine → BaseLoop       │
└──────────────────────────────────────────────────────────────────────┘
                                    ↓
┌──────────────────────────────────────────────────────────────────────┐
│                   Orchestrator Layer                                  │
│                   (BaseLoop)                                          │
│                 主对话循环管理                                         │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  1. runtime.resolve(ctx)                                      │  │
│  │  2. agent.run(messages, tools, system)                        │  │
│  │  3. executor.run(name, args, ctx, tool_view)                  │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
                    ↓           ↓           ↓
         ┌─────────┴──┐    ┌───┴───┐   ┌───┴────────┐
         ↓            ↓    ↓       ↓   ↓            ↓
    ┌────────┐  ┌─────────┐  ┌──────────┐  ┌─────────────────┐
    │ Runtime│  │ BaseAgent│  │Execution│  │  ToolRegistry   │
    │Policy  │  │ (LLM)   │  │  Layer   │  │  (静态目录)      │
    │ Engine │  │         │  │          │  │                 │
    └────────┘  └─────────┘  └──────────┘  └─────────────────┘
                                    ↓
                    ┌───────────────┴───────────────┐
                    ↓                               ↓
             ┌──────────────┐              ┌─────────────────┐
             │ ToolExecutor │              │ SubagentExecutor│
             │  (普通工具)   │              │   (task工具)     │
             └──────────────┘              └─────────────────┘
                    ↓                               ↓
             ┌──────────────┐              ┌─────────────────┐
             │ ToolManager  │              │ SubagentFactory │
             │ + BaseTool   │              │ + SubAgentLoop  │
             └──────────────┘              └─────────────────┘
                                                    ↓
                                        ┌─────────────────────────┐
                                        │  Subagent (隔离执行)     │
                                        │  - 30轮限制              │
                                        │  - 过滤工具集            │
                                        │  - 独立上下文            │
                                        └─────────────────────────┘
```

## 请求流转过程

### 1. 启动阶段（一次性）

```
CLI → build_main_runtime()
    ↓
PluginManager.register_all()
    ↓
ToolRegistry (静态注册)
    ├── CoreToolsPlugin → bash, read_file, edit_file, write_file, todo
    ├── SkillsPlugin → load_skill
    └── SubagentPlugin → read, shell, full 类型声明
    ↓
RuntimePolicyEngine (策略引擎初始化)
    ↓
BaseLoop (编排器创建)
    ├── agent (BaseAgent)
    ├── runtime (RuntimePolicyEngine)
    └── executor (ToolExecutor/SubagentExecutor)
```

### 2. 每轮对话执行流程

```
用户输入消息
    ↓
BaseLoop.loop(messages)
    ↓
RuntimePolicyEngine.resolve(ctx)
    ├── 生成 ToolView (基于模式裁剪工具)
    │   ├── default: core + load_skill + task
    │   ├── safe: 隐藏 bash/edit_file/write_file，task 仅 read
    │   └── swe: 隐藏 todo/write_file/load_skill/task
    ├── 生成 system_prompt (含 skill 元数据)
    └── 返回给 BaseLoop
    ↓
BaseAgent.run(messages, tools=ToolView, system=system_prompt)
    ↓
LLM 返回响应
    ↓
┌─────────────────────────────────────────────────────────────┐
│ 分支判断                                                      │
├─────────────────────────────────────────────────────────────┤
│ 1. 无 tool_use → 直接返回给用户                               │
│ 2. 有 tool_use → ToolExecutor.run()                          │
└─────────────────────────────────────────────────────────────┘
    ↓
ToolExecutor.run(name, args, ctx, tool_view)
    ├── 检查 tool_view.can_call(name) (可见性校验)
    ├── 分支判断
    │   ├── name == "task" → SubagentExecutor
    │   └── 其他 → ToolManager.call()
    ↓
┌─────────────────────────────────────────────────────────────┐
│ 分支 A: 普通工具执行                                          │
├─────────────────────────────────────────────────────────────┤
│ ToolManager.call(name, args)                                 │
│   ├── BaseTool 执行                                           │
│   ├── 日志记录、错误处理、追踪                                 │
│   └── 返回 tool_result                                       │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│ 分支 B: Subagent 执行                                         │
├─────────────────────────────────────────────────────────────┤
│ SubagentExecutor.run()                                       │
│   ├── SubagentFactory.build()                                │
│   │   ├── 懒加载 SubAgentLoop (cache)                        │
│   │   ├── 创建隔离的 ToolManager (过滤工具集)                │
│   │   └── 返回 SubAgentLoop 实例                             │
│   ├── SubAgentLoop.run() (独立执行)                          │
│   │   ├── 最多 30 轮                                         │
│   │   ├── 工具集不含 task (不能再 spawn)                     │
│   │   └── 返回最终文本摘要                                   │
│   └── 返回 tool_result                                       │
└─────────────────────────────────────────────────────────────┘
    ↓
BaseLoop 处理 tool_result
    ├── 添加到消息历史
    ├── 返回 LLM 继续生成
    └── 循环直到对话结束
```

### 3. Skill 加载流转

```
Layer 1 (静态):
SkillLoader.get_descriptions() → system_prompt
    ↓
LLM 看到 skill 描述
    ↓
Layer 2 (动态):
LLM 调用 load_skill(skill_name)
    ↓
ToolExecutor → ToolManager → load_skill 执行
    ↓
skill 内容注入到 tool_result
    ↓
LLM 获得完整 skill 指令
```

## 设计合理性分析

### ✅ 优点

1. **清晰的四层分工**
   - Plugin Layer: 纯声明，不碰运行时
   - Runtime Layer: 统一权限和策略决策
   - Orchestrator Layer: 轻量循环，不做策略
   - Execution Layer: 执行隔离和路由

2. **严格的边界控制**
   - 只有 Runtime 决定可见能力
   - Plugin 永远不构建 loop/agent/client
   - Orchestrator 不做权限、不做策略

3. **良好的扩展性**
   - 新工具: 只需 Plugin.register()
   - 新策略: 只改 Runtime resolver
   - 新 subagent 类型: registry + config

4. **执行隔离**
   - Subagent 懒加载 + 缓存
   - 独立上下文和工具集
   - 递归控制（不能再 spawn）

### ⚠️ 潜在问题

1. **单点策略中心**
   - 所有策略集中在 RuntimePolicyEngine
   - 随着功能增加可能变得臃肿

2. **动态配置限制**
   - 配置只在启动时加载
   - 运行时无法动态调整策略

3. **Subagent 递归限制硬编码**
   - 30 轮限制是固定的
   - 无法根据任务复杂度动态调整

## 总结

当前系统流水线设计**整体合理**，四层架构分工明确，边界清晰。请求流转路径可预测，权限控制集中在 Runtime 层，符合"职责单一"和"开闭原则"。主要优势是扩展性强，各层独立演进。建议的改进点是考虑策略中心的可扩展性，以及支持更灵活的运行时配置调整。