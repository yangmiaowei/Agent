import json
import logging
import re
import traceback
from pathlib import Path

from src.evaluation.agent_loop import SweBenchLoop
from src.evaluation.extract_patch import extract_patch
from src.evaluation.load_data import filter_instances, load_swebench_dataset
from src.evaluation.prompts import build_task_prompt
from src.evaluation.workspace_setup import prepare_instance_workspace, reset_repo
from src.config.loader import load_config
from src.logger.logger import LogSession
from src.setup import build_main_runtime
from src.workspace import reset_workdir, set_workdir

logger = logging.getLogger(__name__)


def _output_path(output_dir: Path, model_name: str, dataset_name: str, split: str) -> Path:
    dataset_slug = dataset_name.split("/")[-1]
    return output_dir / f"{model_name}__{dataset_slug}__{split}.jsonl"


def _load_existing_ids(output_file: Path) -> set[str]:
    if not output_file.exists():
        return set()
    ids = set()
    with open(output_file) as f:
        for line in f:
            if line.strip():
                ids.add(json.loads(line)["instance_id"])
    return ids


def _build_eval_config(base_config: dict | None, *, subagent_enabled: bool) -> dict:
    config = load_config() if base_config is None else json.loads(json.dumps(base_config))
    runtime = config.setdefault("runtime", {})
    runtime["mode"] = "swe"
    runtime["skills_enabled"] = False
    config.setdefault("plugins", {}).setdefault("skills", {})["enabled"] = False
    config.setdefault("plugins", {}).setdefault("subagent", {})["enabled"] = subagent_enabled
    return config


def _rewrite_predictions_without_ids(output_file: Path, drop_ids: set[str]) -> None:
    if not output_file.exists() or not drop_ids:
        return
    kept_lines: list[str] = []
    with open(output_file) as f:
        for line in f:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                kept_lines.append(line)
                continue
            if data.get("instance_id") not in drop_ids:
                kept_lines.append(line)
    with open(output_file, "w") as f:
        f.writelines(kept_lines)


def _patch_touched_files(patch: str) -> list[str]:
    files: list[str] = []
    for line in patch.splitlines():
        if line.startswith("diff --git a/"):
            # Example: diff --git a/path/file.py b/path/file.py
            parts = line.split()
            if len(parts) >= 4 and parts[2].startswith("a/"):
                files.append(parts[2][2:])
    return files


def _passes_patch_gate(instance: dict, patch: str) -> tuple[bool, str]:
    if not patch.strip():
        return False, "empty patch"

    added_lines = sum(1 for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++"))
    if added_lines == 0:
        return False, "patch has no added lines"

    touched_files = _patch_touched_files(patch)
    if touched_files and all(("test" in p.lower() or "tests" in p.lower()) for p in touched_files):
        return False, "patch only touches test files"

    problem = (instance.get("problem_statement") or "").lower()
    if "__dict__" in problem and "__slots__" in problem:
        add_slots = len(re.findall(r"^\+\s*__slots__\s*=", patch, flags=re.MULTILINE))
        del_slots = len(re.findall(r"^-\s*__slots__\s*=", patch, flags=re.MULTILINE))
        if del_slots > add_slots:
            return False, "issue mentions __slots__, but patch removes more __slots__ than it adds"

    return True, "ok"


def run_instance(
    instance: dict,
    *,
    repos_root: Path,
    model_name: str,
    max_rounds: int,
    subagent_enabled: bool = False,
    config: dict | None = None,
    log_dir: Path | None = None,
    max_patch_attempts: int = 2,
    use_patch_gate: bool = True,
):
    repo_path = prepare_instance_workspace(instance, repos_root)
    set_workdir(repo_path)

    eval_config = _build_eval_config(config, subagent_enabled=subagent_enabled)

    patch = ""
    for attempt in range(1, max_patch_attempts + 1):
        # Ensure each retry starts from the exact same base state.
        reset_repo(repo_path, instance["base_commit"])

        attempt_log_dir = log_dir / f"attempt_{attempt}" if log_dir else None
        log_session = LogSession(attempt_log_dir) if attempt_log_dir else None
        main_loop, log_session = build_main_runtime(
            config=eval_config,
            log_session=log_session,
        )
        agent_loop = SweBenchLoop(
            agent=main_loop.agent,
            runtime=main_loop.runtime,
            executor=main_loop.executor,
        )

        prompt = build_task_prompt(instance, strict=attempt > 1)
        messages = [{"role": "user", "content": prompt}]
        agent_loop.loop(messages, logger=log_session.events, max_rounds=max_rounds)

        patch = extract_patch(repo_path)
        if not patch.strip():
            logger.warning(
                "Attempt %d/%d produced empty patch for %s",
                attempt,
                max_patch_attempts,
                instance["instance_id"],
            )
            continue

        if use_patch_gate:
            passed, reason = _passes_patch_gate(instance, patch)
            if not passed:
                logger.warning(
                    "Attempt %d/%d failed patch gate for %s: %s",
                    attempt,
                    max_patch_attempts,
                    instance["instance_id"],
                    reason,
                )
                patch = ""
                continue
            break
        break

    return {
        "instance_id": instance["instance_id"],
        "model_name_or_path": model_name,
        "model_patch": patch,
    }


def run_swebench(
    *,
    dataset_name: str = "princeton-nlp/SWE-bench_Lite",
    split: str = "test",
    output_dir: Path,
    model_name: str = "my-agent",
    repos_root: Path,
    max_rounds: int = 30,
    instance_ids: list[str] | None = None,
    shard_id: int | None = None,
    num_shards: int | None = None,
    subagent_enabled: bool = False,
    config: dict | None = None,
    max_patch_attempts: int = 2,
    use_patch_gate: bool = True,
    rerun_instance_ids: bool = False,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = _output_path(output_dir, model_name, dataset_name, split)
    existing_ids = _load_existing_ids(output_file)

    dataset = load_swebench_dataset(dataset_name, split)
    dataset = filter_instances(dataset, instance_ids)
    rerun_ids = set(instance_ids or []) if rerun_instance_ids else set()
    if rerun_ids:
        _rewrite_predictions_without_ids(output_file, rerun_ids)
        existing_ids -= rerun_ids
    if shard_id is not None and num_shards is not None:
        dataset = dataset.shard(num_shards, shard_id, contiguous=True)

    logger.info("Output: %s", output_file)
    logger.info("Skipping %d completed instances", len(existing_ids))
    logger.info("Running %d instances", len(dataset))

    with open(output_file, "a") as f:
        for instance in dataset:
            instance_id = instance["instance_id"]
            if instance_id in existing_ids:
                continue

            logger.info("Running %s", instance_id)
            instance_log_dir = output_dir / "logs" / instance_id
            try:
                result = run_instance(
                    instance,
                    repos_root=repos_root,
                    model_name=model_name,
                    max_rounds=max_rounds,
                    subagent_enabled=subagent_enabled,
                    config=config,
                    log_dir=instance_log_dir,
                    max_patch_attempts=max_patch_attempts,
                    use_patch_gate=use_patch_gate,
                )
            except Exception:
                logger.error("Failed %s:\n%s", instance_id, traceback.format_exc())
                continue
            finally:
                reset_workdir()

            patch = result.get("model_patch") or ""
            if not patch.strip():
                logger.warning(
                    "No patch produced for %s (see %s). Skipping prediction write.",
                    instance_id,
                    instance_log_dir,
                )
                continue

            print(json.dumps(result), file=f, flush=True)
            existing_ids.add(instance_id)
            logger.info("Finished %s (patch %d bytes)", instance_id, len(patch))

    return output_file
