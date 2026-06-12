from datasets import load_dataset


def load_swebench_dataset(
    dataset_name: str = "princeton-nlp/SWE-bench_Lite",
    split: str = "test",
):
    return load_dataset(dataset_name, split=split)


def filter_instances(dataset, instance_ids: list[str] | None):
    if not instance_ids:
        return dataset
    ids = set(instance_ids)
    return dataset.filter(lambda x: x["instance_id"] in ids)
