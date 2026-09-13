import json
from pathlib import Path

from datasets import load_dataset


def load_swebench_dataset(
    dataset_name: str = "princeton-nlp/SWE-bench_Lite",
    split: str = "test",
):
    return load_dataset(dataset_name, split=split)


def filter_instances(dataset, instance_ids: list[str] | None):
    if not instance_ids:
        return dataset
    # Prefer index-based selection over Dataset.filter(lambda ...), which can
    # involve multiprocess internals in some environments.
    id_to_index = {instance_id: idx for idx, instance_id in enumerate(dataset["instance_id"])}
    missing = [iid for iid in instance_ids if iid not in id_to_index]
    if missing:
        raise ValueError(
            f"{len(missing)} instance id(s) not present in the dataset: "
            f"{', '.join(missing[:5])}{' ...' if len(missing) > 5 else ''}"
        )
    return dataset.select([id_to_index[iid] for iid in instance_ids])


def load_suite(path: str | Path) -> dict:
    """Load a frozen evaluation suite produced by `select_cases`."""
    path = Path(path)
    with open(path) as f:
        suite = json.load(f)
    if not suite.get("cases"):
        raise ValueError(f"Suite {path} contains no cases")
    return suite


def suite_instance_ids(suite: dict) -> list[str]:
    return [case["instance_id"] for case in suite["cases"]]


def suite_case_index(suite: dict) -> dict[str, dict]:
    return {case["instance_id"]: case for case in suite["cases"]}
