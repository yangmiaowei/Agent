# SWE-bench 评测体系说明

本文档说明本项目**如何评测自研 agent 的真实修 bug 能力**：数据从哪来、难度和问题类型怎么分、
从拉仓库到产出 patch 的完整链路、以及这些 patch 如何交给官方 SWE-bench harness 打分。

目标场景是「在一批固定样本上反复优化 agent」，所以整套设计围绕两个要求展开：

- **可复现**：样本一次选定后冻结，每轮优化都在同一批题上对比，分数差异只来自 agent 变化。
- **可归因**：失败必须能追到原因——是没找对文件、改错了逻辑，还是轮数烧完了。

只想快速跑通接入的，看 [SWE-bench 评测接入说明](./SWE-bench评测接入说明.md)；本文讲的是评测体系本身。

---

## 0. 一图看完整闭环

```
                        ┌─ 一次性：选样本 ─┐
select_cases.py  ──────▶ eval_suites/suite_v1.json   （冻结，进 git）
                        └──────────────────┘
                                  │  24 个 instance_id
                                  ▼
run_swebench.py ──▶ runner.py ──▶ 每题：clone → checkout base_commit
                                        → SweBenchLoop 多轮 tool use
                                        → git diff → patch 门禁
                                  │
                                  ├──▶ my-agent__*.jsonl   （官方 predictions 格式）
                                  ├──▶ logs/<iid>/result.json    （每题结局，含失败题）
                                  └──▶ logs/<iid>/attempt_N/events.jsonl  （逐事件日志）
                                  ▼
run_eval.py ──▶ evaluator.py ──▶ swebench.harness.run_evaluation（Docker）
                                  │
                                  └──▶ summary.json   （suite 元数据 + 我们的日志 + 官方判定，三方 join）
                                  ▼
analyze.py  ──────────────────▶ analysis.json  （按根因分桶，指向要改的能力）
```

四个 CLI 各管一段，都在 `src/evaluation/` 下：

| 命令 | 职责 | 产物 |
|------|------|------|
| `select_cases` | 分层抽样，选出固定样本 | `eval_suites/suite_v1.json` |
| `run_swebench` | 跑 agent 推理，产出 patch | `predictions.jsonl` + `result.json` + `events.jsonl` |
| `run_eval` | 调官方 harness 打分（默认可预拉/打完删镜像）并三方 join | `summary.json` |
| `analyze` | 失败按根因分桶 | `analysis.json` |

磁盘紧张时打分务必加 `--sequential`（一题：拉 → 打 → 删）。操作步骤见
[评测接入说明 §4](./SWE-bench评测接入说明.md)。

---

## 1. 数据来源

### 1.1 用的是 SWE-bench Verified，不是 Lite

数据集从 HuggingFace 拉取，默认 `princeton-nlp/SWE-bench_Verified`（`split=test`），
本地缓存在 `~/.cache/huggingface/datasets/`，加载入口是 `load_data.load_swebench_dataset()`。

Verified 是 OpenAI 与 SWE-bench 作者合作、由**专业 Python 开发者逐题人工审核**过的 500 题子集，
剔除了题面描述不足、测试过严等不可解题目。选它而不是 Lite 的决定性原因有两条：

| | SWE-bench Lite (300) | SWE-bench Verified (500) |
|---|---|---|
| 人工难度标注 | **无** | **有**（`difficulty` 字段） |
| gold patch 改动文件数 | 全部 = 1 个文件 | 71 题为多文件 |
| hunk 数 | ≤ 3 | 不限 |
| 改动行数中位数 | 6 行 | 明显更高，且随难度递增 |

Lite 在构造时就被筛成了「单文件、≤3 hunk 的小改动」，难度方差极小。
本项目要求「难度呈阶梯变化」，在 Lite 上**无法成立**——这是实测 300 题统计后得出的结论，
而不是先验判断。

Verified 的 500 题来自 12 个仓库，分布极不均衡：

```
django/django 231 · sympy/sympy 75 · sphinx-doc/sphinx 44 · matplotlib/matplotlib 34
scikit-learn/scikit-learn 32 · 其余 7 个仓库共 84
```

django + sympy 就占了 306/500，所以抽样必须显式限制单仓库配额，否则小样本会退化成
「django 专项测试」。

### 1.2 每题用到的字段

| 字段 | 用途 |
|------|------|
| `instance_id` | 全局唯一 ID，如 `pallets__flask-5014`，贯穿所有产物与日志目录名 |
| `repo` | GitHub 仓库名，决定 clone 地址 |
| `base_commit` | **修复前**的提交；agent 必须从这个状态起步 |
| `problem_statement` | 原始 issue 正文，是**唯一**喂给 agent 的任务描述 |
| `patch` | 官方参考修复（gold patch）。仅用于抽样统计与失败归因，**绝不进入 prompt** |
| `test_patch` | 官方测试改动，由 harness 在打分时注入 |
| `FAIL_TO_PASS` | 修复前失败、修复后必须通过的测试（F2P）——判定是否真的修好了 |
| `PASS_TO_PASS` | 修复前后都必须通过的测试（P2P）——判定是否打崩了别的功能 |
| `difficulty` | 人工标注的预估修复耗时，难度分层的依据 |
| `environment_setup_commit` | harness 构建评测环境用的提交 |

**数据隔离纪律**：`patch` / `test_patch` / `FAIL_TO_PASS` / `PASS_TO_PASS` 全部不进 prompt。
agent 只看到 `problem_statement` 和仓库本身，与真实开发者拿到一个 issue 时的信息量一致。
`select_cases` 会把 `gold_files` 写进 suite 文件，那是给**事后归因**用的（判断 agent 有没有改对文件），
推理阶段读不到。

---

## 2. 难度分层

直接用官方人工标注的 `difficulty` 字段，不自己造难度指标。500 题的分布：

| `difficulty` 原值 | 题数 | 本项目层级 |
|---|---|---|
| `<15 min fix` | 194 | **T1** |
| `15 min - 1 hour` | 261 | **T2** |
| `1-4 hours` | 42 | **T3** |
| `>4 hours` | 3 | 排除 |

`>4 hours` 只有 3 题，撑不起一个层，且从 3 个样本里得不出任何结论，所以 `select_cases.TIERS`
显式把它剔除。

为什么用人工标注而不是自己算代理指标（patch 行数 / 文件数 / F2P 数量）：这些指标只反映
**改动规模**，不反映**定位难度**。一个 3 行的修复可能需要读懂整个继承链才能找到位置。
人工标注的「预估耗时」正好把定位成本算进去了，这是 Verified 相对 Lite 最有价值的地方。

代理指标仍然被记录进 suite 文件（`gold_n_files` / `gold_edit_lines` / `gold_hunks` / `f2p_count`），
用于**验证**分层是否有效。suite_v1 上确实观察到 T1→T3 的 patch 规模单调递增，7 个多文件
gold patch 全部落在 T2/T3。

---

## 3. 问题类型分类

### 3.1 为什么需要

「难度阶梯」只是一个维度。如果 24 题全是崩溃类问题，测出来的就只是「agent 会不会读
traceback」。所以第二个维度是问题类型，让样本覆盖不同的失败形态：

| 类型 | 含义 | 考察的能力 |
|---|---|---|
| `crash` | 本该正常返回，却抛异常 | 读 traceback、顺调用栈定位 |
| `wrong-output` | 不报错，但结果不对 | 理解语义、推理正确行为 |
| `rendering` | 输出格式 / 文本表示 / 文档生成不对 | `__repr__`、LaTeX、Sphinx 这类表示层 |
| `api-behavior` | 缺能力，或要改校验 / 报错信息 | 设计接口、判断「应该」怎样 |
| `other` | 以上都不匹配 | **不参与抽样** |

`other` 是残留桶而非真实类别，从里面抽样会让「按类型对比」失去意义，所以
`problem_types.STRATUM_TYPES` 只包含前四类。

### 3.2 分类器：精度优先于召回

`problem_types.classify()` 是规则式分类器（`TAXONOMY_VERSION = "v4"`），对 500 题的判定：

```
other 161 · wrong-output 137 · crash 124 · api-behavior 50 · rendering 28
```

161 题落进 `other` 看着多，但这是**故意的**：只需要从中挑 24 题，宁可少标也不能错标——
标错会直接让分层失真。v1 版本规则宽松，`rendering` 桶有 81 题，人工复核发现 6 个
`rendering` 标签里 **4 个是错的**。错误几乎全来自同一类原因：**规则匹配到了不描述症状的文本**。

三类噪声源，`_prose()` 会先清掉：

1. **issue 模板样板文**。matplotlib / xarray / sklearn 的 issue 带大段 HTML 注释
   （`<!-- post a Minimal, Complete and Verifiable Example -->`），措辞能命中几乎任何规则。
2. **代码块**。复现脚本里出现 `"""Docstring."""` 或 `ValueError` 说明不了症状是什么。
   例：`pylint-4604` 因为示例代码里有 `"""Docstring."""` 被判成 `rendering`。
3. **环境信息 dump**。xarray 的 `xr.show_versions()` 输出被贴在 `<details>` 块里，
   里面有 `sphinx: 1.7.1`，导致完全无关的 issue 看起来像文档渲染 bug。

清洗后按固定优先级判定，首个命中即返回：

1. **强特征请求信号**（`feature request` / `please support` / 祈使式标题 `Add X`）→ `api-behavior`
2. **traceback** → `crash`。硬证据优先于顺口一提：bug 报告里常在末尾出现
   「顺便说一句这样会更好用」，不该因此被判成特征请求
3. **弱特征请求措辞**（`would be nice to ...`）→ `api-behavior`
4. `crash` / `rendering` / `wrong-output` / `api-behavior` 关键词规则

两个额外约束：
- **标题 bug 否决**：标题含 `doesn't work` / `fails` / `broken` 的，无论开头是什么都不算特征请求
  （`Adding a legend ... doesn't work` 曾被 `add` 前缀误判）。
- `api-behavior` 放在最后且规则收紧：`adding multi_class as an argument` 这类措辞通常是
  bug 报告里**建议的修法**，靠它来判会把 wrong-output 大量误标。

规则每次变动都要 bump `TAXONOMY_VERSION`，suite 文件记录了它构建时的版本。
`tests/test_problem_types.py` 里的用例全部取自真实误标过的 issue，防止规则回退。
`problem_types.explain()` 可以查某题命中了哪条规则，用于复核标签。

---

## 4. 固定样本 suite_v1

### 4.1 抽样算法

```bash
python -m src.evaluation.select_cases \
  --out eval_suites/suite_v1.json --per_cell 2 --repo_cap 3
```

按 `(难度层, 问题类型)` 构成 3 × 4 = 12 个格子，每格取 2 题，共 **24 题**。规模由 token 预算定：
一次 baseline 约 400 万 tokens，再大就没法频繁迭代。

几个关键设计：

- **种子固定**（`--seed 20260911`）：候选先按 `instance_id` 排序再做带种子洗牌，结果完全可复现。
- **难度倒序填格**：先填 T3。T3 只有 42 题，格子最紧；先填简单格会把仓库配额耗光，饿死 T3。
- **仓库配额 `repo_cap=3`**：阻止 django/sympy 主导小样本。
- **两遍填充**：第一遍严格遵守配额；只有当某格因此填不满时，第二遍才放宽，并记一条 warning。
  宁可放宽配额也不留空格子，且放宽这件事必须留痕。

### 4.2 结果

suite_v1 无任何 warning，完全均衡：

```
难度:    T1 8 · T2 8 · T3 8
类型:    crash 6 · rendering 6 · api-behavior 6 · wrong-output 6
仓库:    12 个仓库全覆盖，单仓库最多 3 题（sphinx、sympy）
多文件 gold patch: 7 题（全在 T2/T3）
```

24 题的类型标签经过逐题人工复核，22 个明确正确、2 个边界情况（`sympy-21612` 是 LaTeX
**解析**而非渲染；`xarray-3993` 更像 API 一致性而非纯错误输出）。用于分组统计，可接受。

### 4.3 冻结纪律

`select_cases` 在输出文件已存在时**直接报错**，必须显式 `--force` 才覆盖。
suite 文件进 git（`eval_suites/` 不在 `.gitignore` 里），因为它是对比基准；
`runs/` 不进 git，因为那是每次运行的产物。

---

## 5. 推理流程：从拉仓库到 patch

与官方 `run_api.py`「单次 LLM 调用 → 从回复文本里解析 diff」不同，本项目让 agent
**在真实仓库里多轮操作**，最后用 `git diff` 取 patch。

```bash
python -m src.evaluation.run_swebench \
  --output_dir runs/baseline \
  --suite eval_suites/suite_v1.json \
  --repos_root ./eval_repos \
  --model_name my-agent \
  --max_rounds 30 \
  --max_patch_attempts 1
```

### 5.1 准备工作区（`workspace_setup.py`）

`prepare_instance_workspace()` 为每题准备一个干净仓库，仓库按 `repo` 复用，不重复克隆：

1. **blob-less 浅克隆**：`git clone --filter=blob:none --no-checkout`，只取元数据不取文件内容，
   大仓库（django/sympy）节省大量时间和磁盘。
2. **按 commit 精确 fetch**：`git fetch --depth 1 origin <base_commit>` 后
   `git checkout --force <base_commit>`。只拉需要的那一个提交。
3. **双源 fallback**：镜像源优先，失败退回原始源；识别可重试错误（网络超时等）并退避重试，
   区别于「commit 不存在」这类不可重试错误。
4. **代理透传**：`_git_env()` 把 HTTP(S) 代理传给 git 子进程。
5. **`reset_repo()`**：`git checkout --force <base_commit>` + `git clean -fdxq`，
   保证每次 attempt 从完全相同的基线起步。

> `git clean -fdxq` 会删掉编译产物和 `.so`。对需要 `build_ext --inplace` 的仓库
> （matplotlib、sklearn），attempt 之间要重新编译。

### 5.2 运行 agent（`agent_loop.py` + swe 模式）

prompt 由 `prompts.build_task_prompt()` 构造，只含 `repo` / `instance_id` / `problem_statement`
和操作约束（用已有文件修、别建复现脚本、至少改一个源文件）。

agent 以 `runtime.mode = "swe"` 运行，能力视图被裁剪：

```python
SWE_MODE_BLOCKED_TOOLS = frozenset({"todo", "write_file", "load_skill", "task"})
```

只剩 `bash` / `read_file` / `edit_file`。屏蔽 `write_file` 是为了逼 agent 改**已有文件**而非
新建文件；屏蔽 `todo` / `task` 是为了不在评测里引入额外变量。系统提示词也据此裁剪——
`build_system_prompt(visible_tools=...)` 只在 `task` 真的可用时才介绍它，避免提示词教 agent
用一个被禁用的工具。

**bash 隔离**（`src/tools/bash_policy.py`）。`bash` 在 swe 模式下保留，但必须受限：

baseline 跑完后发现，agent 为了跑测试在 `eval_repos/` 里执行了 `pip install -e .`，
把 pytest、sphinx、xarray 三个被测仓库以 editable 方式装进了共享的 conda 环境，
**替换掉了真正的包**。这既破坏了「每题从同一环境起步」的前提，也污染了共用该解释器的其他项目。

`swe` 模式因此启用 `SWE_POLICY`，两层防护：

1. **命令拦截**：拒绝 `pip/conda/poetry/uv install`、`setup.py install|develop`、
   系统包管理器、`sudo`、`git config --global` 等改环境的命令，并回一句可操作的提示
   （「依赖已装好，直接 `python -m pytest <path>`」）。
   命令行按 `;` `&&` `||` `|` `&` 切段后只匹配**每段的命令头**，所以
   `cd /tmp && pip install -e .` 会被拦下，而 `grep -r "pip install" docs/` 不会误伤。
2. **环境收敛**：即使某条命令绕过第一层（比如 Makefile 内部调 pip），子进程环境里
   `PIP_REQUIRE_VIRTUALENV=1` / `PYTHONNOUSERSITE=1` 会让写入失败；`HOME` / `TMPDIR` /
   `GIT_CONFIG_GLOBAL` 指向临时目录，隔离 `~/.cache`、`~/.gitconfig` 等。
   临时 HOME 刻意放在**工作区之外**——工作区是 git 仓库，其 diff 就是提交的 patch，
   且 attempt 之间会被 `git clean -fdx`。

策略由 `RuntimePolicyEngine.resolve()` 按当前 mode 选取，所以 `default` 模式（人在交互）
下 bash 行为不变，只保留 `rm -rf /`、`shutdown` 这类灾难性命令的拦截。

> 这是**收敛而非内核级沙箱**：`python -c` 仍能写到用户有权限的任何位置。
> 它封堵的是实际发生过的失败模式，并让其余越界行为显式报错。

`SweBenchLoop` 在 `BaseLoop` 之上加了两件事：
- **编辑追踪**：只有 `edit_file` **成功**才记 `has_edited`。失败的编辑不算——否则 agent
  可能把剩余轮数全烧在一直不生效的编辑上，却不再收到提醒。
- **迟期提醒**：距轮数上限 8 轮时，若仍未成功编辑过，注入一条 `FORCE_EDIT_NUDGE`，
  要求停止探索、立刻动手改源码。

### 5.3 取 patch 与门禁

`extract_patch()` 执行 `git diff --no-color`。用 `git diff` 而非解析模型输出，
好处是 patch 一定是**真实文件状态的差异**，不存在格式错误或幻觉行号。
只取已跟踪文件的改动，所以 agent 顺手建的临时文件不会污染 patch。

`runner._passes_patch_gate()` 做通用健全性检查：

- patch 非空
- 有新增行
- 不能只改测试文件

门禁规则刻意保持**与数据集无关**。这里曾经有一条针对 `sympy-20590` 的 `__slots__` 专用规则，
以及 prompt 里硬编码的 `_print_helpers.py` 提示——那是在给要测的东西开后门，测出的分数
不可推广，已在接入评测体系时移除。

未通过门禁时，若还有 attempt 预算就重跑（`--max_patch_attempts`），并换用 `strict=True` 的
更强约束 prompt。

### 5.4 产物与断点续跑

```
runs/baseline/
├── run_meta.json                     # 数据集、suite、配置、token 总量
├── my-agent__SWE-bench_Verified__test.jsonl   # 官方 predictions 格式
├── logs/<instance_id>/
│   ├── result.json                   # 该题结局（每题都有，含失败）
│   └── attempt_N/events.jsonl        # 逐事件日志
├── summary.json                      # run_eval 产出
├── analysis.json                     # analyze 产出
└── harness/                          # 官方 harness 的工作目录
```

`predictions.jsonl` 只包含**成功产出 patch** 的题（官方格式要求），所以失败题在它里面是不可见的。
因此每题都额外写一份 `result.json`，`status` 取值：

| status | 含义 |
|---|---|
| `patch_written` | 出了 patch 并过了门禁 |
| `empty_patch` | agent 跑完但没有任何改动 |
| `gate_rejected` | 有改动但没过门禁 |
| `setup_error` | clone / checkout 失败，agent 根本没跑 |
| `run_error` | 运行中异常，或 LLM 调用最终失败 |

`result.json` 还记录每次 attempt 的终止原因、轮数、各工具调用与报错次数、token 用量、耗时。
`run_error` 与 `empty_patch` 分开是必要的：API 欠费导致的失败如果记成「空 patch」，
会被当成 agent 能力问题混进归因样本。

**断点续跑**：`run_swebench` 启动时读取已有 `predictions.jsonl`，跳过其中已有的 instance。
中断后重跑同一条命令即可接着跑；`--rerun_instance_ids` 可强制重跑指定题目。

---

## 6. 接入官方 harness 打分

判定「是否真的修好了」只信官方 harness，不自己实现。本项目不修改官方仓库，
只作为子进程调用它。

### 6.1 调用方式

```bash
python -m src.evaluation.run_eval --run_dir runs/baseline --run_id baseline-v1
```

`evaluator.run_harness_evaluation()` 拼出并执行：

```bash
python -m swebench.harness.run_evaluation \
  --dataset_name princeton-nlp/SWE-bench_Verified --split test \
  --predictions_path <绝对路径>/my-agent__SWE-bench_Verified__test.jsonl \
  --run_id baseline-v1 --max_workers 4 --timeout 1800 \
  --cache_level env --namespace swebench
```

harness 的产物是**相对进程工作目录**写的，所以调用时把 `cwd` 设成 `runs/<run>/harness/`，
让一次运行的所有文件聚在一起：

```
runs/baseline/harness/
├── my-agent.baseline-v1.json                                   # 汇总报告
└── logs/run_evaluation/baseline-v1/my-agent/<instance_id>/
    ├── report.json        # 逐题判定：applied / resolved / 各测试通过情况
    ├── patch.diff         # 实际应用的 patch
    ├── eval.sh            # 容器内执行的脚本
    ├── run_instance.log   # 容器生命周期日志
    └── test_output.txt    # 测试原始输出
```

harness 每题起一个 Docker 容器，注入 `test_patch` 和我们的 `model_patch`，跑
`FAIL_TO_PASS` 与 `PASS_TO_PASS`。`check_prerequisites()` 会先确认 `swebench` 可导入、
`docker` 在 PATH 上、daemon 可达，避免错误深埋在 Docker 内部。

### 6.2 Apple Silicon 与磁盘：拉镜像 → 打分 → 删镜像

官方预构建镜像 `swebench/sweb.eval.x86_64.*` 只发布 x86_64。它们在 Apple Silicon 上
能通过 Docker Desktop 的 amd64 模拟正常运行，**但 harness 拉镜像时走的是 docker-py 的
`images.pull()` 且不传 platform**，在 arm64 主机上会直接报
`no matching manifest for linux/arm64/v8`。

每张 instance 镜像通常 **4–11 GB**。24 题全留在本地很容易把磁盘打满
（实测曾占满 ~78 GB Docker 镜像层），而且 Docker Desktop 在空间紧张时会静默丢掉
刚拉好、尚未打分的镜像。因此 `run_eval` 默认走：

1. **预拉**（arm64 上默认开启）：`docker pull --platform linux/amd64 …`
2. **打分**：调用官方 harness
3. **删除**该题 instance 镜像（可用 `--keep_images` 保留）

磁盘紧张时用**串行模式**（一题一拉、一打、一删）：

```bash
python -m src.evaluation.run_eval \
  --run_dir runs/baseline --run_id baseline-v1 --sequential
```

镜像名规则：instance_id 里的 `__` 换成 `_1776_`，例如
`pallets__flask-5014` → `swebench/sweb.eval.x86_64.pallets_1776_flask-5014:latest`。
辅助函数在 `evaluator.instance_image_name` / `prepull_instance_images` /
`remove_instance_images`。

不要用 `--namespace none` 本地构建：上游 `make_test_spec` 把 `arch` 硬编码为 `x86_64`，
在 arm64 上本地构建会走 qemu，比直接拉镜像慢得多。

### 6.3 三方 join：summary.json

单独一份 harness 报告只能告诉你「哪些题 resolved」，不足以支撑优化决策。
`run_eval.build_summary()` 把三个来源合到一起：

```
suite 元数据（难度层、问题类型、gold_files）
+ 我们的 result.json（终止原因、轮数、token、patch 改了哪些文件）
+ harness report.json（是否 applied、是否 resolved、哪些测试失败）
```

每题归一个 outcome：

| outcome | 含义 |
|---|---|
| `resolved` | 通过官方判定 |
| `tests_failed` | patch 应用成功，但 F2P 仍失败——**改错了** |
| `regression` | 目标测试过了，但 P2P 崩了——**改出了副作用** |
| `apply_failed` | harness 无法应用该 diff |
| `no_patch` | agent 没产出可判定的改动 |
| `not_graded` | harness 在该题上出错 |

分母按 **suite 要求的题目**取，而不是按有 predictions 的题目，否则「没出 patch」会悄悄
从分母里消失、把分数刷高。summary 同时给出按难度层、按问题类型、按仓库的 resolved 率，
以及 token 消耗。

`--skip_harness` 可以只用已有的 harness 产物重建 summary，不重跑 Docker。

---

## 7. 失败归因

```bash
python -m src.evaluation.analyze --run_dir runs/baseline
```

`analyze.py` 给每个未解决的题打一个根因桶，让人工复核从**分好组的清单**开始，
而不是 24 份原始事件日志。每个桶都指向一项具体能力：

| 桶 | 判据 | 指向的能力 |
|---|---|---|
| `infra_setup` | clone/checkout 失败 | 基础设施，非 agent 问题 |
| `infra_api` | LLM 调用重试后仍失败 | 基础设施，非 agent 问题 |
| `explored_without_editing` | 轮数烧完且从未成功编辑 | 搜索导航效率 + 停止策略 |
| `gave_up_early` | 还有轮数却主动结束且无 patch | 任务框定 / prompt 里的坚持要求 |
| `edit_tool_dead_end` | `edit_file` 反复匹配失败 | 编辑工具人机工效（只支持精确匹配） |
| `gate_rejected` | 出了 patch 但被自家门禁拒 | 门禁规则，或 agent 只改了测试 |
| `apply_failed` | diff 格式坏，harness 应用不上 | diff 生成 / 工作区卫生 |
| `wrong_location` | 改的文件与 gold patch 完全不相交 | **故障定位** |
| `right_file_wrong_fix` | 文件对了但测试不过 | 修复推理 + 对着测试验证 |
| `regression` | 目标测试过了但打崩了别的 | 改动范围控制 / 回归检查 |
| `rounds_exhausted` | 撞轮数上限且 patch 不够好 | 轮数预算或探索效率 |

分桶按**优先级**判定，因为一个题常同时命中多条：`rounds_exhausted` + `no_patch` 的真实
含义是 `explored_without_editing`，报后者才有指导意义。

除了分桶，`analyze.py` 还从 `events.jsonl` 里提取行为信号：bash 与 read_file 的调用比、
用掉的轮数 vs 上限、单题 token、`edit_file` 报错率，以及**是否真的跑过仓库测试**
（`TEST_COMMAND_HINTS`）。最后一项尤其关键——它区分「验证过的修复」和「盲改」。

`analyze.py` 在没有 `summary.json` 时也能工作，退化成只用 `result.json` 报告
agent 侧的失败（无 patch、轮数耗尽、编辑死胡同），这样 Docker 没就绪时也能先看归因。

> `summary.json` 与 `analysis.json` 都带生成时间戳。如果打分是在它们生成**之后**完成的，
> 里面的 `resolved` 是过期占位值，需要重跑 `run_eval` / `analyze`。

---

## 8. 可观测性

为了让上面的归因有数据可用，推理链路上补了这些（原先都没有）：

| 能力 | 位置 | 为什么需要 |
|---|---|---|
| token 记账 | `src/model/usage.py`、`AnthropicClient` | token 预算受限，必须能度量每题花了多少 |
| 退避重试 | `AnthropicClient` | 偶发 429/超时不该让该题静默变成「失败」而污染归因样本 |
| 余额不足不重试 | `AnthropicClient` | 智谱等兼容接口把「余额不足」包装成 `RateLimitError`，重试纯属浪费 |
| 终止原因 | `src/orchestrator/outcome.py` | 区分「想错了」和「轮数不够」必须有这个信号 |
| 逐题 result.json | `runner.py` | 失败题在 predictions 里不可见，而归因恰恰要看失败题 |

`LoopOutcome` 记录停止原因（`end_turn` / `max_rounds` / `error` / `compacted`）、轮数、
各工具调用与报错计数、累计 usage，`BaseLoop` 与 `SweBenchLoop` 共用同一套。

---

## 9. baseline 结果（suite_v1，完整一轮）

配置：`runs/baseline/`，model=`my-agent`，`max_rounds=30`，`max_patch_attempts=1`。

| 阶段 | 状态 |
|---|---|
| 推理 | **24/24**：23 题写出 patch，1 题空 patch（`sympy__sympy-17630`） |
| 打分 | **23/23** 有 patch 的题全部有 harness `report.json` |
| Token | 约 **426 万**（约 17.8 万 / 题） |

### 9.1 真实 resolved 率

按 suite **24 题为分母**（与 `summary.json` 一致）：

| | 数量 | 说明 |
|---|---|---|
| **resolved** | **10** | 官方判定通过 |
| tests_failed | 12 | patch 能应用，F2P 仍失败 |
| regression | 1 | F2P 过了但打崩 P2P（`sphinx-8548`） |
| no_patch | 1 | 空 patch |
| **resolved_rate** | **10/24 = 41.7%** | |

仅看「有 patch 且已打分」的 23 题：**10/23 ≈ 43.5%**。

按难度 / 问题类型：

| | resolved / total |
|---|---|
| T1 / T2 / T3 | **5/8 (62%)** · 2/8 (25%) · 3/8 (38%) |
| api-behavior / wrong-output / crash / rendering | **4/6** · 3/6 · 2/6 · **1/6** |

通过的 10 题：

| 层 | 类型 | instance |
|---|---|---|
| T1 | api-behavior | `pallets__flask-5014` |
| T1 | crash | `psf__requests-1724`、`pylint-dev__pylint-6903` |
| T1 | wrong-output | `pylint-dev__pylint-7277`、`pytest-dev__pytest-7982` |
| T2 | api-behavior | `matplotlib__matplotlib-26342` |
| T2 | rendering | `sympy__sympy-21612` |
| T3 | api-behavior | `django__django-16560`、`scikit-learn__scikit-learn-25102` |
| T3 | wrong-output | `astropy__astropy-14369` |

T1 明显好于 T2/T3；api-behavior 最好；rendering 最弱（仅 1/6）。
失败题的 patch **几乎都能 apply**——瓶颈在定位/修对，不在 diff 格式。
极端例：`xarray-4356` F2P 0/8，并打崩 **604** 个 P2P。

### 9.2 失败归因摘要（`analysis.json`）

| 桶 | 数量 | 指向的能力 |
|---|---|---|
| `right_file_wrong_fix` | 11 | 修复推理 + 对着测试验证 |
| `wrong_location` | 1 | 故障定位（`django-15957`） |
| `explored_without_editing` | 1 | 探索效率（`sympy-17630`） |
| `regression` | 1 | 改动范围（`sphinx-8548`） |

其它信号：

- 未解决题里多数打满 30 轮
- **仅 7/24** 在事件日志里跑过仓库测试 → 「改完不验证」
- bash 调用远多于 `read_file`
- baseline 中 agent 曾 `pip install -e .` 污染宿主 → 已用 swe 模式 `bash_policy` 拦截（§5.2）

---

## 10. 相关文件

| 文件 | 作用 |
|---|---|
| `src/evaluation/select_cases.py` | 分层抽样，产出冻结 suite |
| `src/evaluation/problem_types.py` | 问题类型规则分类器（v4） |
| `src/evaluation/load_data.py` | HuggingFace 数据集与 suite 加载 |
| `src/evaluation/run_swebench.py` | 推理 CLI |
| `src/evaluation/runner.py` | 批量推理、断点续跑、patch 门禁、result.json |
| `src/evaluation/workspace_setup.py` | clone / checkout / 镜像 fallback / reset |
| `src/evaluation/agent_loop.py` | SWE 专用循环（编辑追踪 + 迟期提醒） |
| `src/evaluation/prompts.py` | 任务 prompt |
| `src/evaluation/extract_patch.py` | `git diff` 取 patch |
| `src/evaluation/patch_utils.py` | diff 解析（文件、行数、hunk、是否只碰测试） |
| `src/evaluation/evaluator.py` | 官方 harness 子进程封装；镜像名 / 预拉 / 打分后删除 |
| `src/evaluation/run_eval.py` | 打分 + 镜像生命周期 + 三方 join → summary.json |
| `src/evaluation/analyze.py` | 失败根因分桶 → analysis.json |
| `src/tools/bash_policy.py` | bash 按 mode 的执行策略与环境隔离 |
| `src/runtime/resolver.py` | 按 mode 裁剪工具可见性、选择 bash 策略 |
| `src/orchestrator/outcome.py` | `LoopOutcome`：终止原因、轮数、工具统计、usage |
| `src/model/usage.py` | token 记账 |
| `eval_suites/suite_v1.json` | 冻结的 24 题样本 |
