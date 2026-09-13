# Agent 接入 SWE-bench 评测说明

本文档说明如何将本项目的 tool-using agent 接入 [SWE-bench](https://github.com/SWE-bench/SWE-bench)
官方评测：生成兼容的 `predictions.jsonl`，再用官方 harness 打分。

样本分层、难度/问题类型、推理与打分闭环的设计说明见
[SWE-bench 评测体系说明](./SWE-bench评测体系说明.md)。日常迭代请以冻结样本
`eval_suites/suite_v1.json`（Verified，24 题）为准。

---

## 1. 整体架构

与官方 `run_api.py`（单次 LLM 调用 → 从文本解析 diff）不同，本方案在真实仓库里
多轮工具调用，最后用 `git diff` 取 patch。

```
SWE-bench Verified (HuggingFace) + suite_v1.json
        │
        ▼
  clone / checkout base_commit（eval_repos/）
        │
        ▼
  SweBenchLoop（mode=swe：bash / read_file / edit_file）
        │
        ▼
  git diff → model_patch → predictions.jsonl
        │
        ▼
  run_eval → swebench.harness.run_evaluation（Docker）
        │
        ▼
  summary.json + analysis.json
```

| 维度 | 官方 `run_api.py` | 本 agent |
|------|-------------------|----------|
| 输入 | 预处理 `text` prompt | `problem_statement` + 真实 repo |
| 执行 | 一次 API 调用 | 多轮 tool use |
| patch 来源 | `extract_diff(completion)` | `git diff` |
| 环境 | 无 repo | 每题独立 checkout |

### 核心模块

| 文件 | 作用 |
|------|------|
| `select_cases.py` | 分层抽样，写出冻结 suite |
| `run_swebench.py` / `runner.py` | 批量推理、断点续跑、patch 门禁、`result.json` |
| `workspace_setup.py` | 浅克隆、按 commit checkout、镜像源 fallback |
| `agent_loop.py` | SWE 循环：编辑追踪 + 迟期提醒 |
| `extract_patch.py` | `git diff` 取 patch |
| `run_eval.py` / `evaluator.py` | 调官方 harness；预拉/打分后删镜像；写 `summary.json` |
| `analyze.py` | 失败根因分桶 → `analysis.json` |
| `bash_policy.py` | swe 模式下拦截 `pip install` 等改环境命令 |

---

## 2. Predictions 格式

Harness 接受 `.jsonl`，每行最少：

```json
{
  "instance_id": "pallets__flask-5014",
  "model_name_or_path": "my-agent",
  "model_patch": "diff --git a/...\n..."
}
```

空 patch **不写入** predictions（会记在 `logs/<iid>/result.json`，status=`empty_patch`）。

文件名：`{model_name}__{dataset_slug}__{split}.jsonl`  
例：`runs/baseline/my-agent__SWE-bench_Verified__test.jsonl`

---

## 3. 环境准备

### 3.1 依赖

```bash
# Agent 侧（示例：anaconda base 已装 datasets / anthropic / swebench）
pip install datasets python-dotenv anthropic

# 官方 harness（editable 安装本地 SWE-bench clone，勿改其源码）
cd /path/to/SWE-bench && pip install -e .
```

### 3.2 环境变量（项目根 `.env`）

```env
ANTHROPIC_API_KEY=...
ANTHROPIC_BASE_URL=...   # 兼容 Anthropic 协议的网关时可设
MODEL=...

# 访问 GitHub 不稳定时建议配置
https_proxy=http://127.0.0.1:7890
http_proxy=http://127.0.0.1:7890
```

### 3.3 Docker

Harness 需要 Docker Desktop 已启动。Apple Silicon 上用官方 **x86_64** 预构建镜像
（amd64 模拟）；`run_eval` 会按需 `docker pull --platform linux/amd64`，
**打分后默认删除**该题镜像。磁盘紧时务必加 `--sequential`。

---

## 4. 使用方法

### 4.1 推荐：冻结 suite 上跑一轮

```bash
cd /path/to/Agent

# 1) 推理（可断点续跑）
PYTHONPATH=. python -m src.evaluation.run_swebench \
  --output_dir runs/baseline \
  --suite eval_suites/suite_v1.json \
  --repos_root ./eval_repos \
  --model_name my-agent \
  --max_rounds 30 \
  --max_patch_attempts 1

# 2) 打分（一题一拉、一打、一删）
PYTHONPATH=. python -m src.evaluation.run_eval \
  --run_dir runs/baseline \
  --run_id baseline-v1 \
  --sequential

# 3) 失败归因
PYTHONPATH=. python -m src.evaluation.analyze --run_dir runs/baseline
```

### 4.2 单题 smoke

```bash
PYTHONPATH=. python -m src.evaluation.run_swebench \
  --output_dir runs/smoke \
  --repos_root ./eval_repos \
  --model_name my-agent \
  --dataset princeton-nlp/SWE-bench_Verified \
  --instance_ids pallets__flask-5014 \
  --max_rounds 30 \
  --max_patch_attempts 1
```

### 4.3 强制重跑已有 instance

predictions 里已有记录时会被跳过；加 `--rerun_instance_ids` 会先删掉对应行再跑：

```bash
PYTHONPATH=. python -m src.evaluation.run_swebench \
  --output_dir runs/baseline \
  --suite eval_suites/suite_v1.json \
  --repos_root ./eval_repos \
  --model_name my-agent \
  --instance_ids sympy__sympy-17630 \
  --rerun_instance_ids \
  --max_rounds 30 \
  --max_patch_attempts 1
```

### 4.4 仅重建汇总（不跑 Docker）

```bash
PYTHONPATH=. python -m src.evaluation.run_eval \
  --run_dir runs/baseline --run_id baseline-v1 --skip_harness
```

### 4.5 常用 CLI 参数（`run_swebench`）

| 参数 | 说明 | 默认 |
|------|------|------|
| `--suite` | 冻结样本 JSON；会覆盖 dataset/split/instance 列表 | 无 |
| `--dataset` | HuggingFace 数据集 | `princeton-nlp/SWE-bench_Lite`（有 suite 时以 suite 为准） |
| `--output_dir` | 运行目录（predictions + logs + run_meta） | 必填 |
| `--repos_root` | repo 克隆根目录 | `eval_repos` |
| `--model_name` | 写入 `model_name_or_path` | `my-agent` |
| `--max_rounds` | 每题最大轮数 | `30` |
| `--max_patch_attempts` | 空 patch / 门禁失败重试 | `2` |
| `--instance_ids` | 只跑指定题 | 全部 / suite 内全部 |
| `--shard_id` / `--num_shards` | 分片 | 无 |
| `--subagent` | 启用 subagent | 关 |
| `--disable_patch_gate` | 关闭 patch 门禁 | 门禁默认开 |
| `--rerun_instance_ids` | 强制重跑 `--instance_ids` | 关 |

`run_eval` 额外参数：`--sequential`、`--keep_images`、`--no_prepull`、`--skip_harness`。

---

## 5. 设计要点

### 5.1 动态工作区

每题把 `WORKDIR` 切到 `eval_repos/{owner}__{repo}`；`bash` / `read_file` / `edit_file`
都在该目录执行。每次 attempt 前 `reset_repo`（`checkout --force` + `clean -fdxq`）。

### 5.2 SWE runtime（`mode=swe`）

- 关闭 skills；subagent 默认关（除非 `--subagent`）
- 隐藏 `todo` / `write_file` / `task` / `load_skill`
- 保留 `bash` / `read_file` / `edit_file`
- **bash 隔离**：拒绝 `pip/conda/poetry install`、`setup.py develop`、`sudo` 等；
  `HOME`/`TMPDIR` 指到临时目录，避免污染宿主 site-packages（见 `bash_policy.py`）

### 5.3 SweBenchLoop

- 只有 **成功** 的 `edit_file` 才记 `has_edited`
- 距轮数上限 8 轮仍未成功编辑时注入强制改源码提醒

### 5.4 Patch 门禁（数据集无关）

写入 predictions 前：

- 非空
- 至少有新增行
- 不能只改测试文件

不再使用任何「某一题专用」启发式（曾有的 sympy `__slots__` 规则已删除）。

### 5.5 日志与结果

```
runs/<run>/
├── run_meta.json
├── my-agent__SWE-bench_Verified__test.jsonl
├── logs/<instance_id>/
│   ├── result.json                 # 每题结局（含失败）
│   └── attempt_N/events.jsonl
├── summary.json                    # run_eval 产出
├── analysis.json                   # analyze 产出
└── harness/                        # 官方 harness 工作目录
```

---

## 6. 常见问题

### 6.1 Git clone 失败

浅克隆 + 按 commit fetch；镜像源 / 原始源双 fallback；支持 `.env` 代理；
失败清理半成品目录，合法 repo 可复用。

### 6.2 空 patch

强化 prompt + 编辑追踪/提醒；空 patch 不进 predictions，靠
`--max_patch_attempts` 重试；结局记在 `result.json`。

### 6.3 arm64 上 harness 报 no matching manifest

不要改官方 SWE-bench 仓库。用本仓库 `run_eval`（自动
`docker pull --platform linux/amd64`），或手动预拉后再跑 harness。

### 6.4 Docker 镜像把磁盘打满

每张 instance 镜像约 4–11 GB。使用 `--sequential`（默认打完即删）。
已打过分的镜像可：

```bash
docker images 'swebench/sweb.eval.x86_64.*' -q | xargs -r docker rmi -f
```

### 6.5 重跑被跳过

加 `--rerun_instance_ids`。

### 6.6 退出时 ResourceTracker 警告

Python 3.12 + `datasets`/`multiprocess` 的退出噪音，一般不影响产物。

---

## 7. 目录结构（运行后）

```
Agent/
├── eval_suites/suite_v1.json       # 冻结的 24 题样本（进 git）
├── eval_repos/                     # 克隆的仓库（gitignore）
├── runs/                           # 每次运行产物（gitignore）
│   └── baseline/
│       ├── my-agent__SWE-bench_Verified__test.jsonl
│       ├── logs/ …
│       ├── summary.json
│       └── harness/
└── src/evaluation/
```

---

## 8. 快速检查清单

- [ ] `.env` 中 API（与可选代理）已配置
- [ ] Docker Desktop 运行中；磁盘留足单题镜像空间（建议 ≥15 GB 空闲）
- [ ] `run_swebench --suite eval_suites/suite_v1.json` 产出非空 predictions
- [ ] `run_eval --sequential` 写出 `summary.json`，`resolved` / `outcomes` 合理
- [ ] `analyze` 写出 `analysis.json`；失败桶与优化方向对应
