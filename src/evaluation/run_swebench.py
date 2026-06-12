#!/usr/bin/env python3
"""Run the agent on SWE-bench instances and write predictions for harness evaluation."""

import logging
from argparse import ArgumentParser
from pathlib import Path

from src.evaluation.runner import run_swebench

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        default="princeton-nlp/SWE-bench_Lite",
        help="HuggingFace SWE-bench dataset name",
    )
    parser.add_argument("--split", default="test", help="Dataset split")
    parser.add_argument(
        "--output_dir",
        type=Path,
        required=True,
        help="Directory for predictions jsonl",
    )
    parser.add_argument(
        "--repos_root",
        type=Path,
        default=Path("eval_repos"),
        help="Directory to clone SWE-bench repos into",
    )
    parser.add_argument(
        "--model_name",
        default="my-agent",
        help="Identifier written to model_name_or_path in predictions",
    )
    parser.add_argument(
        "--max_rounds",
        type=int,
        default=30,
        help="Maximum agent turns per instance",
    )
    parser.add_argument(
        "--instance_ids",
        nargs="+",
        default=None,
        help="Optional subset of instance IDs to run",
    )
    parser.add_argument("--shard_id", type=int, default=None)
    parser.add_argument("--num_shards", type=int, default=None)
    parser.add_argument(
        "--no_subagent",
        action="store_true",
        help="Disable subagent delegation for lower cost",
    )
    args = parser.parse_args()

    if (args.shard_id is None) != (args.num_shards is None):
        parser.error("--shard_id and --num_shards must be set together")

    output_file = run_swebench(
        dataset_name=args.dataset,
        split=args.split,
        output_dir=args.output_dir,
        model_name=args.model_name,
        repos_root=args.repos_root.resolve(),
        max_rounds=args.max_rounds,
        instance_ids=args.instance_ids,
        shard_id=args.shard_id,
        num_shards=args.num_shards,
        subagent_enabled=not args.no_subagent,
    )
    print(f"Predictions written to {output_file}")
    print()
    print("Evaluate with SWE-bench harness:")
    print(
        "  python -m swebench.harness.run_evaluation \\"
        f"\n    --dataset_name {args.dataset} \\"
        f"\n    --split {args.split} \\"
        f"\n    --predictions_path {output_file} \\"
        "\n    --max_workers 4 \\"
        "\n    --run_id <your-run-id>"
    )


if __name__ == "__main__":
    main()
