import json
import logging
import traceback
from pathlib import Path

from src.evaluation.extract_patch import extract_patch
from src.evaluation.load_data import filter_instances, load_swebench_dataset
from src.evaluation.prompts import build_task_prompt
from src.evaluation.workspace_setup import prepare_instance_workspace
from src.config.loader import load_config
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
    config.setdefault("plugins", {}).setdefault("subagent", {})["enabled"] = subagent_enabled
    return config


def run_instance(
    instance: dict,
    *,
    repos_root: Path,
    model_name: str,
    max_rounds: int,
    subagent_enabled: bool = True,
    config: dict | None = None,
):
    repo_path = prepare_instance_workspace(instance, repos_root)
    set_workdir(repo_path)

    eval_config = _build_eval_config(config, subagent_enabled=subagent_enabled)
    agent_loop, log_session = build_main_runtime(config=eval_config)

    prompt = build_task_prompt(instance)
    messages = [{"role": "user", "content": prompt}]
    agent_loop.loop(messages, logger=log_session.events, max_rounds=max_rounds)

    patch = extract_patch(repo_path)
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
    subagent_enabled: bool = True,
    config: dict | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = _output_path(output_dir, model_name, dataset_name, split)
    existing_ids = _load_existing_ids(output_file)

    dataset = load_swebench_dataset(dataset_name, split)
    dataset = filter_instances(dataset, instance_ids)
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
            try:
                result = run_instance(
                    instance,
                    repos_root=repos_root,
                    model_name=model_name,
                    max_rounds=max_rounds,
                    subagent_enabled=subagent_enabled,
                    config=config,
                )
            except Exception:
                logger.error("Failed %s:\n%s", instance_id, traceback.format_exc())
                result = {
                    "instance_id": instance_id,
                    "model_name_or_path": model_name,
                    "model_patch": "",
                }
            finally:
                reset_workdir()

            print(json.dumps(result), file=f, flush=True)
            logger.info(
                "Finished %s (patch %d bytes)",
                instance_id,
                len(result.get("model_patch") or ""),
            )

    return output_file
