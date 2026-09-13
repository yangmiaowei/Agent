import json
import logging
import time
import traceback
from datetime import datetime
from pathlib import Path

from src.config.loader import load_config
from src.evaluation.agent_loop import SweBenchLoop
from src.evaluation.extract_patch import extract_patch
from src.evaluation.load_data import filter_instances, load_swebench_dataset
from src.evaluation.patch_utils import patch_stats
from src.evaluation.prompts import build_task_prompt
from src.evaluation.workspace_setup import prepare_instance_workspace, reset_repo
from src.logger.logger import LogSession
from src.model.usage import Usage
from src.orchestrator.outcome import STOP_ERROR
from src.setup import build_main_runtime
from src.tools.bash_policy import reset_bash_policy
from src.workspace import reset_workdir, set_workdir

logger = logging.getLogger(__name__)

# Per-instance terminal status, recorded in result.json for every instance
# (including the ones that never make it into predictions).
STATUS_PATCH_WRITTEN = "patch_written"
STATUS_EMPTY_PATCH = "empty_patch"
STATUS_GATE_REJECTED = "gate_rejected"
STATUS_SETUP_ERROR = "setup_error"
STATUS_RUN_ERROR = "run_error"


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


def _passes_patch_gate(instance: dict, patch: str) -> tuple[bool, str]:
    """Generic, dataset-agnostic sanity checks. No per-instance heuristics here:
    anything issue-specific would bias the benchmark it is meant to measure."""
    if not patch.strip():
        return False, "empty patch"

    stats = patch_stats(patch)
    if stats["added_lines"] == 0:
        return False, "patch has no added lines"
    if stats["files"] and not stats["source_files"]:
        return False, "patch only touches test files"

    return True, "ok"


def _write_result(log_dir: Path | None, result: dict) -> None:
    if log_dir is None:
        return
    log_dir.mkdir(parents=True, exist_ok=True)
    with open(log_dir / "result.json", "w") as f:
        json.dump(result, f, indent=2)


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
) -> dict:
    started = time.time()
    result = {
        "instance_id": instance["instance_id"],
        "repo": instance["repo"],
        "base_commit": instance["base_commit"],
        "model_name_or_path": model_name,
        "status": STATUS_RUN_ERROR,
        "model_patch": "",
        "patch_stats": {},
        "gate": {"enabled": use_patch_gate, "passed": False, "reason": "not evaluated"},
        "attempts": [],
        "usage_total": Usage().to_dict(),
        "error": None,
        "config": {
            "max_rounds": max_rounds,
            "max_patch_attempts": max_patch_attempts,
            "patch_gate": use_patch_gate,
            "subagent": subagent_enabled,
        },
        "started_at": datetime.now().isoformat(),
    }

    def finalize(status: str, *, error: str | None = None) -> dict:
        result["status"] = status
        result["error"] = error
        result["duration_s"] = round(time.time() - started, 1)
        result["finished_at"] = datetime.now().isoformat()
        _write_result(log_dir, result)
        return result

    try:
        repo_path = prepare_instance_workspace(instance, repos_root)
    except Exception:
        logger.error("Workspace setup failed for %s", instance["instance_id"])
        return finalize(STATUS_SETUP_ERROR, error=traceback.format_exc(limit=5))

    set_workdir(repo_path)
    eval_config = _build_eval_config(config, subagent_enabled=subagent_enabled)

    total_usage = Usage()
    patch = ""
    gate_reason = "not evaluated"
    gate_passed = False

    try:
        for attempt in range(1, max_patch_attempts + 1):
            attempt_started = time.time()
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
            outcome = agent_loop.loop(
                messages, logger=log_session.events, max_rounds=max_rounds
            )

            attempt_patch = extract_patch(repo_path)
            if attempt_patch.strip():
                gate_passed, gate_reason = (
                    _passes_patch_gate(instance, attempt_patch)
                    if use_patch_gate
                    else (True, "gate disabled")
                )
            else:
                gate_passed, gate_reason = False, "empty patch"

            attempt_record = {
                "attempt": attempt,
                "duration_s": round(time.time() - attempt_started, 1),
                "patch_stats": patch_stats(attempt_patch) if attempt_patch.strip() else {},
                "gate_passed": gate_passed,
                "gate_reason": gate_reason,
                "had_successful_edit": agent_loop.has_edited,
                **(outcome.to_dict() if outcome else {}),
            }
            result["attempts"].append(attempt_record)
            if outcome and outcome.usage:
                total_usage.add(Usage(**{
                    k: v for k, v in outcome.usage.items()
                    if k in Usage.__dataclass_fields__
                }))
            result["usage_total"] = total_usage.to_dict()
            _write_result(log_dir, result)  # checkpoint after each attempt

            if gate_passed:
                patch = attempt_patch
                break

            # LLM/API failure: do not burn remaining attempts; surface as run_error.
            if outcome and outcome.stop_reason == STOP_ERROR:
                result["model_patch"] = ""
                result["patch_stats"] = {}
                result["gate"] = {
                    "enabled": use_patch_gate,
                    "passed": False,
                    "reason": gate_reason,
                }
                return finalize(STATUS_RUN_ERROR, error=outcome.error)

            logger.warning(
                "Attempt %d/%d rejected for %s: %s (stop_reason=%s, rounds=%s)",
                attempt,
                max_patch_attempts,
                instance["instance_id"],
                gate_reason,
                outcome.stop_reason if outcome else "?",
                outcome.rounds if outcome else "?",
            )
    except Exception:
        logger.error("Agent run failed for %s", instance["instance_id"])
        return finalize(STATUS_RUN_ERROR, error=traceback.format_exc(limit=5))
    finally:
        reset_workdir()
        reset_bash_policy()  # also removes the scratch HOME bash ran under

    result["model_patch"] = patch
    result["patch_stats"] = patch_stats(patch) if patch.strip() else {}
    result["gate"] = {
        "enabled": use_patch_gate,
        "passed": gate_passed,
        "reason": gate_reason,
    }

    if patch.strip():
        return finalize(STATUS_PATCH_WRITTEN)
    if gate_reason == "empty patch":
        return finalize(STATUS_EMPTY_PATCH)
    return finalize(STATUS_GATE_REJECTED)


def run_swebench(
    *,
    dataset_name: str = "princeton-nlp/SWE-bench_Lite",
    split: str = "test",
    output_dir: Path,
    model_name: str = "my-agent",
    repos_root: Path,
    max_rounds: int = 30,
    instance_ids: list[str] | None = None,
    suite_name: str | None = None,
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

    run_meta = {
        "dataset": dataset_name,
        "split": split,
        "suite": suite_name,
        "predictions_file": output_file.name,
        "model_name": model_name,
        "n_instances": len(dataset),
        "max_rounds": max_rounds,
        "max_patch_attempts": max_patch_attempts,
        "patch_gate": use_patch_gate,
        "subagent": subagent_enabled,
        "instance_ids": instance_ids,
        "started_at": datetime.now().isoformat(),
    }
    with open(output_dir / "run_meta.json", "w") as f:
        json.dump(run_meta, f, indent=2)

    logger.info("Output: %s", output_file)
    logger.info("Skipping %d completed instances", len(existing_ids))
    logger.info("Running %d instances", len(dataset))

    status_counts: dict[str, int] = {}
    grand_total = Usage()

    with open(output_file, "a") as f:
        for instance in dataset:
            instance_id = instance["instance_id"]
            if instance_id in existing_ids:
                continue

            logger.info("Running %s", instance_id)
            instance_log_dir = output_dir / "logs" / instance_id
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

            status = result["status"]
            status_counts[status] = status_counts.get(status, 0) + 1
            grand_total.add(Usage(**{
                k: v for k, v in result["usage_total"].items()
                if k in Usage.__dataclass_fields__
            }))

            patch = result.get("model_patch") or ""
            if not patch.strip():
                logger.warning(
                    "No patch for %s (status=%s, see %s)",
                    instance_id,
                    status,
                    instance_log_dir,
                )
                continue

            print(
                json.dumps({
                    "instance_id": instance_id,
                    "model_name_or_path": model_name,
                    "model_patch": patch,
                }),
                file=f,
                flush=True,
            )
            existing_ids.add(instance_id)
            logger.info("Finished %s (patch %d bytes)", instance_id, len(patch))

    run_meta["finished_at"] = datetime.now().isoformat()
    run_meta["status_counts"] = status_counts
    run_meta["usage_total"] = grand_total.to_dict()
    with open(output_dir / "run_meta.json", "w") as f:
        json.dump(run_meta, f, indent=2)

    logger.info("Status counts: %s", status_counts)
    logger.info(
        "Total tokens: %s (in=%s out=%s cache_read=%s) across %s LLM calls",
        grand_total.total_tokens,
        grand_total.input_tokens,
        grand_total.output_tokens,
        grand_total.cache_read_input_tokens,
        grand_total.calls,
    )

    return output_file
