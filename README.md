# Agent

Tool-using agent：多轮工具调用、插件化能力注册、Runtime 按模式裁剪工具视图，并接入 [SWE-bench](https://github.com/SWE-bench/SWE-bench) 官方评测。

## 功能概览

- **交互式 Agent**：bash / 读写改文件 / todo / skills / subagent
- **Runtime 策略**：`default` / `safe` / `swe` 等模式下裁剪可见工具与 system prompt
- **SWE-bench 管线**：冻结 suite → 真实仓库多轮修复 → `git diff` 出 patch → harness 打分 → 失败归因

## 目录结构

```
.
├── src/                    # 主代码（包名 src）
│   ├── cli/                # 交互入口
│   ├── setup.py            # 组装 runtime（Bootstrap）
│   ├── agent/              # LLM Agent
│   ├── orchestrator/       # 主循环 BaseLoop
│   ├── runtime/            # 策略引擎、SkillLoader、ToolView
│   ├── plugins/            # 能力注册（core tools / skills / subagent）
│   ├── registry/           # 工具与 subagent 类型目录
│   ├── execution/          # Tool / Subagent 执行
│   ├── tools/              # 具体工具实现
│   ├── memory/             # context compact、todo
│   ├── model/              # Anthropic 客户端
│   ├── prompts/            # system prompt
│   ├── config/             # agent_config.json
│   ├── skills/             # Skill 资源（非 Python 包）
│   └── evaluation/         # SWE-bench 推理 / 打分 / 分析
├── tests/                  # 离线单元测试
├── docs/                   # 设计与评测说明
├── eval_suites/            # 冻结评测样本（如 suite_v1.json）
├── eval_repos/             # 评测用仓库克隆（gitignore）
├── runs/                   # 推理与打分产物（gitignore）
├── predictions/            # 历史 predictions（gitignore）
├── WORKDIR/                # 交互运行工作区（gitignore）
└── old/                    # 历史实验脚本（非当前主路径）
```

流水线设计见 [`docs/system-pipeline.md`](docs/system-pipeline.md)。

## 环境要求

- Python **≥ 3.10**
- Anthropic 兼容 API（官方或网关）
- 跑官方 harness 打分时需要 **Docker**（Apple Silicon 上为 amd64 模拟镜像）

## 安装

```bash
cd /path/to/Agent

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt
# 或可编辑安装（推荐）：
pip install -e ".[dev]"
```

SWE-bench harness（打分用，建议本地 editable）：

```bash
cd /path/to/SWE-bench && pip install -e .
# 或：pip install -e ".[eval]"
```

### 环境变量

在项目根创建 `.env`：

```env
ANTHROPIC_API_KEY=...
ANTHROPIC_BASE_URL=...   # 兼容 Anthropic 协议的网关时可设
MODEL=...

# 访问 GitHub / HuggingFace 不稳定时建议配置代理
https_proxy=http://127.0.0.1:7890
http_proxy=http://127.0.0.1:7890
```

可选运行时开关（覆盖 `src/config/agent_config.json`）：

| 变量 | 作用 |
|------|------|
| `AGENT_MODE` | runtime 模式（如 `default` / `swe`） |
| `SAFE_MODE` | 安全模式 |
| `SKILLS_ENABLED` | 是否启用 skills |
| `SUBAGENT_ENABLED` | 是否启用 subagent |
| `SUBAGENT_TYPES` | 逗号分隔类型，如 `read,shell,full` |

## 快速开始

### 交互式 Agent

```bash
python -m src.cli.main
```

输入 `q` / `exit` / 空行退出。工作目录默认在 `WORKDIR/`。

### 单元测试

```bash
pytest
```

## SWE-bench 评测

日常迭代以冻结样本 [`eval_suites/suite_v1.json`](eval_suites/suite_v1.json)（Verified，24 题）为准。

```bash
# 1) 推理（可断点续跑）
python -m src.evaluation.run_swebench \
  --output_dir runs/baseline \
  --suite eval_suites/suite_v1.json \
  --repos_root ./eval_repos \
  --model_name my-agent \
  --max_rounds 30 \
  --max_patch_attempts 1

# 2) 打分（需 Docker；建议 --sequential）
python -m src.evaluation.run_eval \
  --run_dir runs/baseline \
  --run_id baseline-v1 \
  --sequential

# 3) 失败归因
python -m src.evaluation.analyze --run_dir runs/baseline
```

单题 smoke：

```bash
python -m src.evaluation.run_swebench \
  --output_dir runs/smoke \
  --repos_root ./eval_repos \
  --model_name my-agent \
  --dataset princeton-nlp/SWE-bench_Verified \
  --instance_ids pallets__flask-5014 \
  --max_rounds 30 \
  --max_patch_attempts 1
```

更完整的格式、断点续跑与 harness 说明：

- [`docs/SWE-bench评测接入说明.md`](docs/SWE-bench评测接入说明.md)
- [`docs/SWE-bench评测体系说明.md`](docs/SWE-bench评测体系说明.md)

## 相关文档

| 文档 | 内容 |
|------|------|
| [`docs/system-pipeline.md`](docs/system-pipeline.md) | 系统流水线 |
| [`docs/plugins.md`](docs/plugins.md) | 插件机制 |
| [`docs/task.md`](docs/task.md) / [`docs/task_cursor.md`](docs/task_cursor.md) | Task / Subagent |
| [`docs/context _compact.md`](docs/context%20_compact.md) | Context compact |
| [`docs/待优化.md`](docs/待优化.md) | 优化笔记 |
