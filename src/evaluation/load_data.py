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
    selected_indices = [id_to_index[iid] for iid in instance_ids if iid in id_to_index]
    return dataset.select(selected_indices)
