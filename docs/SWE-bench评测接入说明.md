# Agent 接入 SWE-bench 评测说明

本文档说明如何将本项目的 tool-using agent 接入 [SWE-bench](https://github.com/SWE-bench/SWE-bench) 官方评测流程：生成与官方兼容的 `predictions.jsonl`，再使用 SWE-bench harness 进行评测。

---

## 1. 整体架构

与 SWE-bench 官方 `run_api.py`（单次 LLM 调用 → 从文本解析 diff）不同，本方案基于**多轮工具调用 agent**，在真实仓库中修改代码，最后用 `git diff` 提取 patch。

```
SWE-bench 数据集 (HuggingFace)
        │
        ▼
  每个 instance 准备 repo（clone + checkout base_commit）
        │
        ▼
  SweBenchLoop 运行 agent（bash / read_file / edit_file）
        │
        ▼
  git diff → model_patch
        │
        ▼
  predictions.jsonl（官方格式）
        │
        ▼
  swebench.harness.run_evaluation（Docker 评测）
```

### 与官方脚本的对比

| 维度 | 官方 `run_api.py` | 本 agent |
|------|-------------------|----------|
| 输入 | 预处理好的 `text` prompt | `problem_statement` + 真实 repo |
| 执行 | 一次 API 调用 | 多轮 tool use |
| patch 来源 | `extract_diff(completion)` | `git diff` |
| 环境 | 无 repo | 每个 instance 独立 repo |

### 核心模块

| 文件 | 作用 |
|------|------|
| `src/evaluation/run_swebench.py` | CLI 入口 |
| `src/evaluation/runner.py` | 批量推理、断点续跑、patch 门禁 |
| `src/evaluation/workspace_setup.py` | clone 镜像仓库、checkout、代理与重试 |
| `src/evaluation/agent_loop.py` | SWE 专用 agent 循环（编辑追踪、强制提醒） |
| `src/evaluation/prompts.py` | 构造 issue 修复 prompt |
| `src/evaluation/extract_patch.py` | `git diff` 提取 patch |
| `src/evaluation/load_data.py` | 加载 HuggingFace 数据集 |
| `src/workspace.py` | 动态 `WORKDIR`（每个 instance 切换 repo 目录） |

---

## 2. Predictions 格式

SWE-bench harness 接受 `.jsonl`，每行一条 JSON，**最少需要**：

```json
{
  "instance_id": "sympy__sympy-20590",
  "model_name_or_path": "my-agent",
  "model_patch": "diff --git a/...\n..."
}
```

- `instance_id`：SWE-bench 题目 ID
- `model_name_or_path`：模型/系统标识（用于日志目录命名）
- `model_patch`：unified diff（`git diff` 格式）

空 patch 的 instance 不会被写入 predictions，评测时也会被跳过。

输出文件命名：`{model_name}__{dataset_slug}__{split}.jsonl`  
例如：`predictions/my-agent__SWE-bench_Lite__test.jsonl`

---

## 3. 环境准备

### 3.1 依赖

```bash
# Agent 项目
pip install datasets python-dotenv anthropic  # 及项目已有依赖

# SWE-bench 评测（在 SWE-bench 仓库目录）
cd /path/to/SWE-bench
pip install -e .
```

### 3.2 环境变量

在项目根目录 `.env` 中配置（`run_swebench` 会自动加载）：

```env
ANTHROPIC_API_KEY=...
ANTHROPIC_BASE_URL=...   # 若使用第三方代理
MODEL=...

# 访问 GitHub 不稳定时建议配置代理
https_proxy=http://127.0.0.1:7890
http_proxy=http://127.0.0.1:7890
```

### 3.3 Docker

官方 harness 评测需要 Docker 已安装并运行。

---

## 4. 使用方法

### 4.1 单题 smoke test（推荐先做）

```bash
cd /path/to/Agent

python -m src.evaluation.run_swebench \
  --output_dir ./predictions \
  --repos_root ./eval_repos \
  --model_name my-agent \
  --instance_ids sympy__sympy-20590 \
  --max_rounds 30 \
  --max_patch_attempts 3
```

### 4.2 强制重跑已有 instance

若 predictions 中已有该题记录，需加 `--rerun_instance_ids`：

```bash
python -m src.evaluation.run_swebench \
  --output_dir ./predictions \
  --repos_root ./eval_repos \
  --model_name my-agent \
  --instance_ids sympy__sympy-20590 \
  --rerun_instance_ids \
  --max_rounds 30 \
  --max_patch_attempts 3
```

### 4.3 全量 SWE-bench Lite（300 题，可分片）

```bash
python -m src.evaluation.run_swebench \
  --output_dir ./predictions \
  --repos_root ./eval_repos \
  --model_name my-agent \
  --shard_id 0 --num_shards 4
```

### 4.4 官方 harness 评测

```bash
cd /path/to/SWE-bench

python -m swebench.harness.run_evaluation \
  --dataset_name princeton-nlp/SWE-bench_Lite \
  --split test \
  --predictions_path /path/to/Agent/predictions/my-agent__SWE-bench_Lite__test.jsonl \
  --max_workers 4 \
  --run_id my-agent-v1
```

评测报告示例字段：

- `resolved_instances`：测试全部通过的数量
- `unresolved_instances`：patch 已应用但测试未通过
- `empty_patch_instances`：空 patch（本方案默认不写入）

### 4.5 常用 CLI 参数

| 参数 | 说明 | 默认 |
|------|------|------|
| `--dataset` | HuggingFace 数据集名 | `princeton-nlp/SWE-bench_Lite` |
| `--output_dir` | predictions 输出目录 | 必填 |
| `--repos_root` | repo 克隆目录 | `eval_repos` |
| `--model_name` | 写入 `model_name_or_path` | `my-agent` |
| `--max_rounds` | 每题最大 agent 轮数 | `30` |
| `--max_patch_attempts` | 空 patch / 门禁失败时重试次数 | `2` |
| `--instance_ids` | 只跑指定题目 | 全部 |
| `--shard_id` / `--num_shards` | 分片并行 | 无 |
| `--subagent` | 启用 subagent | 默认关闭 |
| `--disable_patch_gate` | 关闭 patch 质量门禁 | 默认开启 |
| `--rerun_instance_ids` | 强制重跑 `--instance_ids` 中的题 | 默认关闭 |

---

## 5. 设计要点

### 5.1 动态工作区

每个 instance 将 `WORKDIR` 切换到对应 repo 目录（`eval_repos/{owner}__{repo}`），`bash` / `read_file` / `edit_file` 均在该目录下执行。

### 5.2 SWE 专用 runtime（`mode=swe`）

评测时自动：

- 关闭 skills、subagent（除非 `--subagent`）
- 隐藏 `todo`、`write_file`、`task`、`load_skill`，减少无效探索
- 保留 `bash`、`read_file`、`edit_file`

### 5.3 SweBenchLoop

- 追踪是否调用过 `edit_file`
- 临近轮数上限时注入提醒，要求必须编辑源码
- 每次 attempt 从 `base_commit` 重置 repo，保证可复现

### 5.4 Patch 质量门禁（默认开启）

写入 predictions 前检查：

- patch 非空
- 至少有一行新增（`+`）
- 不能只改测试文件
- 对 `__dict__` + `__slots__` 类 issue：若删除的 `__slots__` 多于新增，则拒绝（避免方向性错误 patch）

### 5.5 日志

每题日志目录：`predictions/logs/{instance_id}/attempt_{n}/events.jsonl`

---

## 6. 遇到的问题与当前解法

### 6.1 Git clone 失败

**现象**：`https://git@github.com/...` 认证失败，或 `Empty reply from server`。

**原因**：未配置 `GITHUB_TOKEN` 时 URL 拼错；大仓库 + 网络不稳定。

**解法**：

- 无 token 时使用公开 URL `https://github.com/swe-bench-repos/...`
- 浅克隆（`--filter=blob:none`）+ 按 commit fetch
- 自动重试 + 双源 fallback（镜像仓库 / 原始仓库）
- 支持 `https_proxy` / `http_proxy`（shell 或 `.env`）
- 失败时清理不完整目录；已有合法 repo 则复用

### 6.2 产出空 patch

**现象**：agent 跑满轮数但 `model_patch` 为空。

**原因**：

- agent 只探索、写测试脚本，未 `edit_file` 改 tracked 源码
- `git diff` 不包含未跟踪文件

**解法**：

- 强化 prompt：禁止建独立测试脚本，必须改已有源码
- `SweBenchLoop` 编辑追踪 + 临近上限强制提醒
- 空 patch 不写入 predictions，支持 `--max_patch_attempts` 重试
- `read_file` 支持 `offset`，避免 agent 反复读文件开头浪费轮数

### 6.3 Patch 方向错误（resolved=0）

**现象**：有 patch、harness 能跑，但 `resolved_instances=0`（如 sympy-20590 删除 `__slots__` 而非在 mixin 中补充）。

**解法**：

- patch 门禁：对 `__slots__` 类 issue 拒绝“删多于增”的 patch
- prompt 中提示检查 `sympy/core/_print_helpers.py` 等 mixin

### 6.4 重跑被跳过

**现象**：`Skipping N completed instances`，未真正重跑。

**解法**：使用 `--rerun_instance_ids`，先从 predictions 中删除对应记录再跑。

### 6.5 退出时 ResourceTracker 警告

**现象**：`AttributeError: '_thread.RLock' object has no attribute '_recursion_count'`。

**说明**：Python 3.12 + `multiprocess` / `datasets` 的已知退出噪音，一般不影响 predictions 与评测结果。

---

## 7. 目录结构（运行后）

```
Agent/
├── eval_repos/                    # 克隆的 SWE-bench 镜像仓库（可复用）
│   └── sympy__sympy/
├── predictions/
│   ├── my-agent__SWE-bench_Lite__test.jsonl
│   └── logs/
│       └── sympy__sympy-20590/
│           ├── attempt_1/events.jsonl
│           └── attempt_2/events.jsonl
└── src/evaluation/                # 评测模块源码
```

---

## 8. 后续可优化方向

- 在 instance 容器内运行 agent（与 SWE-agent 一致，环境更贴近评测）
- 提交前本地跑 SWE-bench 提供的 FAIL_TO_PASS 测试子集
- 按 repo 缓存依赖安装，减少重复 clone 时间
- 更强 patch 门禁（关键词 → 期望修改文件启发式）

---

## 9. 快速检查清单

- [ ] `.env` 中 API 与代理已配置
- [ ] 单题 smoke test 产出非空 `model_patch`
- [ ] `predictions/*.jsonl` 每行含 `instance_id`、`model_name_or_path`、`model_patch`
- [ ] 在 SWE-bench 目录执行 `run_evaluation`，查看 `resolved_instances`
