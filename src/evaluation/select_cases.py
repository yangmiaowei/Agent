#!/usr/bin/env python3
"""Build a frozen, stratified SWE-bench evaluation suite.

The suite is stratified on two axes:

  * difficulty  - SWE-bench Verified's human annotation (`difficulty` field),
                  which is why Verified is the default dataset. Lite has no
                  difficulty labels and is filtered to single-file patches, so
                  it cannot express a difficulty gradient.
  * problem type - rule-based taxonomy from `problem_types.py`.

Selection is deterministic given `--seed`, and the result is written to a JSON
file that is meant to be committed and never regenerated, so every optimisation
round is measured on exactly the same instances.

Example:
    python -m src.evaluation.select_cases \
        --out eval_suites/suite_v1.json --per_cell 2 --repo_cap 3
"""

import json
import logging
import random
from argparse import ArgumentParser
from collections import Counter
from datetime import datetime
from pathlib import Path

from src.evaluation.load_data import load_swebench_dataset
from src.evaluation.patch_utils import patch_stats
from src.evaluation.problem_types import (
    STRATUM_TYPES,
    TAXONOMY_VERSION,
    classify,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Difficulty tiers, easiest first. ">4 hours" is deliberately excluded: Verified
# only has 3 such instances, too few to support a stratum or to draw any
# conclusion from.
TIERS: list[tuple[str, str]] = [
    ("T1", "<15 min fix"),
    ("T2", "15 min - 1 hour"),
    ("T3", "1-4 hours"),
]
TIER_BY_DIFFICULTY = {difficulty: tier for tier, difficulty in TIERS}


def _as_list(value):
    if isinstance(value, str):
        return json.loads(value)
    return list(value or [])


def build_pool(dataset) -> list[dict]:
    """Annotate every instance with the metadata needed for stratification."""
    pool = []
    for inst in dataset:
        difficulty = inst.get("difficulty")
        tier = TIER_BY_DIFFICULTY.get(difficulty)
        ptype = classify(inst["problem_statement"])
        gold = patch_stats(inst["patch"])
        pool.append({
            "instance_id": inst["instance_id"],
            "repo": inst["repo"],
            "difficulty": difficulty,
            "tier": tier,
            "problem_type": ptype,
            "gold_files": gold["files"],
            "gold_n_files": gold["n_files"],
            "gold_edit_lines": gold["added_lines"] + gold["removed_lines"],
            "gold_hunks": gold["hunks"],
            "f2p_count": len(_as_list(inst["FAIL_TO_PASS"])),
            "p2p_count": len(_as_list(inst["PASS_TO_PASS"])),
            "problem_statement_len": len(inst["problem_statement"]),
        })
    return pool


def select(
    pool: list[dict],
    *,
    per_cell: int,
    repo_cap: int,
    seed: int,
    types: tuple[str, ...] = STRATUM_TYPES,
) -> tuple[list[dict], list[str]]:
    """Greedy constrained stratified pick.

    Cells are (tier, problem_type). Within a cell, candidates are ordered to
    spread repositories: least-used repo first, ties broken by a seeded shuffle.
    A global per-repo cap stops django/sympy (306 of Verified's 500 instances)
    from dominating a small suite.
    """
    rng = random.Random(seed)
    by_cell: dict[tuple[str, str], list[dict]] = {}
    for case in pool:
        if case["tier"] is None or case["problem_type"] not in types:
            continue
        by_cell.setdefault((case["tier"], case["problem_type"]), []).append(case)

    for candidates in by_cell.values():
        candidates.sort(key=lambda c: c["instance_id"])  # stable base order
        rng.shuffle(candidates)

    selected: list[dict] = []
    repo_counts: Counter = Counter()
    warnings: list[str] = []

    # Hardest tier first: its cells are the scarcest, so it gets first claim on
    # the repo budget. Filling easy cells first would starve T3.
    cells = [
        (tier, ptype)
        for tier, _ in reversed(TIERS)
        for ptype in types
    ]

    for tier, ptype in cells:
        candidates = by_cell.get((tier, ptype), [])
        picked = 0
        # Pass 1 respects the repo cap; pass 2 relaxes it only if the cell
        # would otherwise be short, so a cell is never silently left empty.
        for enforce_cap in (True, False):
            if picked >= per_cell:
                break
            ordered = sorted(candidates, key=lambda c: repo_counts[c["repo"]])
            for case in ordered:
                if picked >= per_cell:
                    break
                if case in selected:
                    continue
                if enforce_cap and repo_counts[case["repo"]] >= repo_cap:
                    continue
                selected.append(case)
                repo_counts[case["repo"]] += 1
                picked += 1
            if picked < per_cell and enforce_cap:
                warnings.append(
                    f"cell ({tier}, {ptype}): repo cap {repo_cap} too tight, "
                    f"relaxing to fill {per_cell - picked} slot(s)"
                )
        if picked < per_cell:
            warnings.append(
                f"cell ({tier}, {ptype}): only {picked}/{per_cell} available "
                f"(pool has {len(candidates)})"
            )

    selected.sort(key=lambda c: (c["tier"], c["problem_type"], c["instance_id"]))
    return selected, warnings


def summarize(cases: list[dict]) -> dict:
    return {
        "by_tier": dict(Counter(c["tier"] for c in cases)),
        "by_problem_type": dict(Counter(c["problem_type"] for c in cases)),
        "by_repo": dict(Counter(c["repo"] for c in cases)),
        "multi_file_gold": sum(1 for c in cases if c["gold_n_files"] > 1),
    }


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="princeton-nlp/SWE-bench_Verified")
    parser.add_argument("--split", default="test")
    parser.add_argument("--out", type=Path, required=True, help="Suite JSON path")
    parser.add_argument("--per_cell", type=int, default=2, help="Cases per (tier, type) cell")
    parser.add_argument("--repo_cap", type=int, default=3, help="Max cases per repository")
    parser.add_argument("--seed", type=int, default=20260911)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing suite (frozen suites should not be regenerated)",
    )
    args = parser.parse_args()

    if args.out.exists() and not args.force:
        parser.error(
            f"{args.out} already exists. A frozen suite must stay fixed so results "
            f"stay comparable; pass --force only if you intend to replace it."
        )

    dataset = load_swebench_dataset(args.dataset, args.split)
    pool = build_pool(dataset)

    labelled = [c for c in pool if c["tier"] and c["problem_type"] in STRATUM_TYPES]
    logger.info(
        "Pool: %d instances, %d eligible (tier-labelled and typed)",
        len(pool),
        len(labelled),
    )
    if not labelled:
        parser.error(
            f"No instances in {args.dataset} carry a 'difficulty' label. "
            f"Use SWE-bench_Verified, which is human-annotated."
        )

    cases, warnings = select(
        pool,
        per_cell=args.per_cell,
        repo_cap=args.repo_cap,
        seed=args.seed,
    )
    for warning in warnings:
        logger.warning("%s", warning)

    suite = {
        "name": args.out.stem,
        "dataset": args.dataset,
        "split": args.split,
        "seed": args.seed,
        "per_cell": args.per_cell,
        "repo_cap": args.repo_cap,
        "taxonomy_version": TAXONOMY_VERSION,
        "tiers": [{"tier": t, "difficulty": d} for t, d in TIERS],
        "problem_types": list(STRATUM_TYPES),
        "size": len(cases),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "warnings": warnings,
        "distribution": summarize(cases),
        "cases": cases,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(suite, f, indent=2)

    print(f"\nWrote {len(cases)} cases to {args.out}\n")
    print(f'{"tier":5} {"type":14} {"repo":26} {"files":>5} {"lines":>6} {"F2P":>4}  instance_id')
    for c in cases:
        print(
            f'{c["tier"]:5} {c["problem_type"]:14} {c["repo"]:26} '
            f'{c["gold_n_files"]:5} {c["gold_edit_lines"]:6} {c["f2p_count"]:4}  {c["instance_id"]}'
        )
    print("\nDistribution:", json.dumps(suite["distribution"], indent=2))


if __name__ == "__main__":
    main()
