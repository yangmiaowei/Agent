#!/usr/bin/env python3
"""Score a run with the SWE-bench harness and fold the results back in.

Reads `run_meta.json` from a run directory produced by `run_swebench`, invokes
the official harness, then joins three sources into one `summary.json`:

    suite metadata (difficulty tier, problem type)
  + our per-instance result.json (stop reason, rounds, tokens, patch stats)
  + harness grading (applied / resolved / which tests failed)

Without this join the harness report is just a list of instance ids, which is
not enough to tell whether a failure was the agent giving up, patching the
wrong file, or breaking unrelated tests.

Example:
    python -m src.evaluation.run_eval \
        --run_dir predictions --run_id baseline-v1 --suite eval_suites/suite_v1.json
"""

import json
import logging
from argparse import ArgumentParser
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from src.evaluation.evaluator import (
    HarnessUnavailable,
    PREBUILT_NAMESPACE,
    check_prerequisites,
    default_namespace,
    instance_report_path,
    load_instance_report,
    load_report,
    needs_platform_prepull,
    prepull_instance_images,
    remove_instance_images,
    report_path,
    run_harness_evaluation,
)
from src.evaluation.load_data import load_suite, suite_case_index

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Outcome of one case after grading, most severe failure first.
OUTCOME_RESOLVED = "resolved"
OUTCOME_TESTS_FAILED = "tests_failed"      # patch applied, FAIL_TO_PASS still failing
OUTCOME_REGRESSION = "regression"          # target tests pass, PASS_TO_PASS broke
OUTCOME_APPLY_FAILED = "apply_failed"      # harness could not apply the diff
OUTCOME_NO_PATCH = "no_patch"              # agent produced nothing to grade
OUTCOME_NOT_GRADED = "not_graded"          # harness errored on this instance


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def _prediction_ids(predictions_path: Path) -> list[str]:
    ids = []
    with open(predictions_path) as f:
        for line in f:
            if line.strip():
                ids.append(json.loads(line)["instance_id"])
    return ids


def _ungraded_ids(
    work_dir: Path, run_id: str, model_name: str, instance_ids: list[str]
) -> list[str]:
    return [
        iid
        for iid in instance_ids
        if not instance_report_path(work_dir, run_id, model_name, iid).exists()
    ]


def _grade_batch(
    *,
    predictions_path: Path,
    run_meta: dict,
    run_id: str,
    work_dir: Path,
    instance_ids: list[str] | None,
    max_workers: int,
    timeout: int,
    cache_level: str,
    namespace: str,
) -> int:
    return run_harness_evaluation(
        predictions_path=predictions_path,
        dataset_name=run_meta["dataset"],
        split=run_meta["split"],
        run_id=run_id,
        work_dir=work_dir,
        max_workers=max_workers,
        instance_ids=instance_ids,
        timeout=timeout,
        cache_level=cache_level,
        namespace=namespace,
    )


def _run_harness_with_image_lifecycle(
    *,
    predictions_path: Path,
    run_meta: dict,
    run_id: str,
    work_dir: Path,
    grade_ids: list[str],
    max_workers: int,
    timeout: int,
    cache_level: str,
    namespace: str,
    prepull: bool,
    sequential: bool,
    remove_after: bool,
) -> None:
    """Pull (if needed) → grade → remove instance images.

    Sequential mode grades one instance at a time and deletes its image
    immediately, which is the only safe pattern on a disk-constrained host
    (each sweb.eval image is multi-GB).
    """
    if not grade_ids:
        logger.info("Nothing left to grade (all predictions already have reports).")
        return

    if namespace == "none":
        # Local builds are shared base/env layers; do not try to manage them.
        _grade_batch(
            predictions_path=predictions_path,
            run_meta=run_meta,
            run_id=run_id,
            work_dir=work_dir,
            instance_ids=grade_ids,
            max_workers=max_workers,
            timeout=timeout,
            cache_level=cache_level,
            namespace=namespace,
        )
        return

    if sequential:
        for iid in grade_ids:
            logger.info("Sequential grade: %s", iid)
            if prepull:
                prepull_instance_images([iid], namespace=namespace)
            code = _grade_batch(
                predictions_path=predictions_path,
                run_meta=run_meta,
                run_id=run_id,
                work_dir=work_dir,
                instance_ids=[iid],
                max_workers=1,
                timeout=timeout,
                cache_level=cache_level,
                namespace=namespace,
            )
            if code != 0:
                logger.warning("Harness exited %d on %s", code, iid)
            if remove_after:
                remove_instance_images([iid], namespace=namespace)
        return

    if prepull:
        prepull_instance_images(grade_ids, namespace=namespace)
    code = _grade_batch(
        predictions_path=predictions_path,
        run_meta=run_meta,
        run_id=run_id,
        work_dir=work_dir,
        instance_ids=grade_ids,
        max_workers=max_workers,
        timeout=timeout,
        cache_level=cache_level,
        namespace=namespace,
    )
    if code != 0:
        logger.warning(
            "Harness exited with code %d; summarising whatever it produced.", code
        )
    if remove_after:
        # Remove every image we asked to grade, including ones that errored —
        # a failed run still leaves a multi-GB image on disk.
        remove_instance_images(grade_ids, namespace=namespace)


def classify_outcome(result: dict | None, grading: dict | None) -> str:
    if grading is None:
        if result and not (result.get("model_patch") or "").strip():
            return OUTCOME_NO_PATCH
        return OUTCOME_NOT_GRADED
    if grading.get("resolved"):
        return OUTCOME_RESOLVED
    if not grading.get("patch_exists"):
        return OUTCOME_NO_PATCH
    if not grading.get("patch_successfully_applied"):
        return OUTCOME_APPLY_FAILED

    tests = grading.get("tests_status") or {}
    f2p = tests.get("FAIL_TO_PASS", {})
    p2p = tests.get("PASS_TO_PASS", {})
    if not f2p.get("failure") and p2p.get("failure"):
        return OUTCOME_REGRESSION
    return OUTCOME_TESTS_FAILED


def _rate(resolved: int, total: int) -> float:
    return round(resolved / total, 3) if total else 0.0


def _group_rates(cases: list[dict], key: str) -> dict:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for case in cases:
        buckets[case.get(key) or "unknown"].append(case)
    return {
        name: {
            "total": len(group),
            "resolved": sum(1 for c in group if c["outcome"] == OUTCOME_RESOLVED),
            "resolved_rate": _rate(
                sum(1 for c in group if c["outcome"] == OUTCOME_RESOLVED), len(group)
            ),
        }
        for name, group in sorted(buckets.items())
    }


def build_summary(
    *,
    run_dir: Path,
    work_dir: Path,
    run_id: str,
    run_meta: dict,
    suite: dict | None,
    aggregate: dict | None,
) -> dict:
    model_name = run_meta["model_name"]
    suite_cases = suite_case_index(suite) if suite else {}

    # Grade every case the suite asked for, not just those with predictions,
    # so instances that produced no patch still appear in the denominator.
    instance_ids = list(suite_cases) or (run_meta.get("instance_ids") or [])
    if not instance_ids and aggregate:
        instance_ids = aggregate.get("submitted_ids", [])

    cases = []
    for instance_id in instance_ids:
        result = _read_json(run_dir / "logs" / instance_id / "result.json")
        grading = load_instance_report(work_dir, run_id, model_name, instance_id)
        meta = suite_cases.get(instance_id, {})
        attempts = (result or {}).get("attempts") or []
        last = attempts[-1] if attempts else {}
        tests = (grading or {}).get("tests_status") or {}

        cases.append({
            "instance_id": instance_id,
            "repo": meta.get("repo") or (result or {}).get("repo"),
            "tier": meta.get("tier"),
            "difficulty": meta.get("difficulty"),
            "problem_type": meta.get("problem_type"),
            "outcome": classify_outcome(result, grading),
            "run_status": (result or {}).get("status"),
            "stop_reason": last.get("stop_reason"),
            "rounds": last.get("rounds"),
            "attempts": len(attempts),
            "tool_calls": last.get("tool_calls") or {},
            "tool_errors": last.get("tool_errors") or {},
            "had_successful_edit": last.get("had_successful_edit"),
            "gate_reason": (result or {}).get("gate", {}).get("reason"),
            "tokens": ((result or {}).get("usage_total") or {}).get("total_tokens"),
            "duration_s": (result or {}).get("duration_s"),
            "patch_files": ((result or {}).get("patch_stats") or {}).get("files", []),
            "gold_files": meta.get("gold_files", []),
            "gold_n_files": meta.get("gold_n_files"),
            "f2p_failed": len(tests.get("FAIL_TO_PASS", {}).get("failure", [])),
            "f2p_passed": len(tests.get("FAIL_TO_PASS", {}).get("success", [])),
            "p2p_failed": len(tests.get("PASS_TO_PASS", {}).get("failure", [])),
        })

    resolved = sum(1 for c in cases if c["outcome"] == OUTCOME_RESOLVED)
    total_tokens = sum(c["tokens"] or 0 for c in cases)

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "suite": suite.get("name") if suite else None,
        "dataset": run_meta.get("dataset"),
        "split": run_meta.get("split"),
        "model_name": model_name,
        "max_rounds": run_meta.get("max_rounds"),
        "max_patch_attempts": run_meta.get("max_patch_attempts"),
        "graded_at": datetime.now().isoformat(timespec="seconds"),
        "total": len(cases),
        "resolved": resolved,
        "resolved_rate": _rate(resolved, len(cases)),
        "outcomes": dict(Counter(c["outcome"] for c in cases)),
        "by_tier": _group_rates(cases, "tier"),
        "by_problem_type": _group_rates(cases, "problem_type"),
        "by_repo": _group_rates(cases, "repo"),
        "tokens_total": total_tokens,
        "tokens_per_case": round(total_tokens / len(cases)) if cases else 0,
        "harness_report": aggregate,
        "cases": cases,
    }


def print_summary(summary: dict) -> None:
    print(f"\n=== {summary['run_id']}: "
          f"{summary['resolved']}/{summary['total']} resolved "
          f"({summary['resolved_rate']:.1%}) ===\n")

    print("Outcomes:")
    for name, count in sorted(summary["outcomes"].items(), key=lambda kv: -kv[1]):
        print(f"  {name:16} {count}")

    for label, key in (("difficulty tier", "by_tier"), ("problem type", "by_problem_type")):
        print(f"\nBy {label}:")
        for name, stats in summary[key].items():
            print(f"  {name:16} {stats['resolved']}/{stats['total']} "
                  f"({stats['resolved_rate']:.0%})")

    print(f"\nTokens: {summary['tokens_total']:,} total, "
          f"{summary['tokens_per_case']:,} per case")

    unresolved = [c for c in summary["cases"] if c["outcome"] != OUTCOME_RESOLVED]
    if unresolved:
        print(f"\nUnresolved ({len(unresolved)}):")
        print(f'  {"tier":5} {"type":13} {"outcome":14} {"stop":12} {"rnd":>4}  instance_id')
        for c in sorted(unresolved, key=lambda c: (c["tier"] or "", c["instance_id"])):
            print(f'  {c["tier"] or "-":5} {c["problem_type"] or "-":13} '
                  f'{c["outcome"]:14} {c["stop_reason"] or "-":12} '
                  f'{c["rounds"] if c["rounds"] is not None else "-":>4}  {c["instance_id"]}')


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--run_dir", type=Path, required=True,
                        help="Run directory produced by run_swebench")
    parser.add_argument("--run_id", required=True, help="Harness run id")
    parser.add_argument("--suite", type=Path, default=None,
                        help="Suite JSON; defaults to the one named in run_meta.json")
    parser.add_argument("--max_workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--cache_level", default="env",
                        choices=["none", "base", "env", "instance"])
    parser.add_argument("--namespace", default=None,
                        help=('Docker image namespace. Defaults to "swebench", '
                              "the official prebuilt images. Pass \"none\" to "
                              "build them locally instead (much slower). On "
                              "arm64 the prebuilt images must be pulled with "
                              "`docker pull --platform linux/amd64` first"))
    parser.add_argument("--skip_harness", action="store_true",
                        help="Only rebuild summary.json from existing harness output")
    parser.add_argument(
        "--prepull",
        action="store_true",
        default=None,
        help="Pre-pull images with --platform linux/amd64 before grading "
             "(default: on when the host is arm64)",
    )
    parser.add_argument(
        "--no_prepull",
        action="store_true",
        help="Never pre-pull; only works when images are already local",
    )
    parser.add_argument(
        "--sequential",
        action="store_true",
        help="Grade one instance at a time: pull → grade → remove. "
             "Use this when disk space is tight (each image is multi-GB)",
    )
    parser.add_argument(
        "--keep_images",
        action="store_true",
        help="Keep instance Docker images after grading "
             "(default: delete each image once its report is written)",
    )
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    run_meta = _read_json(run_dir / "run_meta.json")
    if run_meta is None:
        parser.error(
            f"{run_dir / 'run_meta.json'} not found. Point --run_dir at a "
            f"directory produced by `python -m src.evaluation.run_swebench`."
        )

    predictions_path = run_dir / run_meta.get("predictions_file", "")
    if not predictions_path.exists():
        parser.error(f"Predictions file not found: {predictions_path}")

    suite_path = args.suite
    if suite_path is None and run_meta.get("suite"):
        candidate = Path("eval_suites") / f"{run_meta['suite']}.json"
        if candidate.exists():
            suite_path = candidate
    suite = load_suite(suite_path) if suite_path else None
    if suite:
        logger.info("Joining against suite %s (%d cases)", suite["name"], suite["size"])
    else:
        logger.warning(
            "No suite supplied: per-tier and per-type breakdowns will be empty."
        )

    work_dir = run_dir / "harness"
    model_name = run_meta["model_name"]
    namespace = args.namespace or default_namespace()
    remove_after = not args.keep_images
    if args.no_prepull:
        prepull = False
    elif args.prepull:
        prepull = True
    else:
        prepull = needs_platform_prepull() and namespace == PREBUILT_NAMESPACE

    if not args.skip_harness:
        try:
            check_prerequisites()
        except HarnessUnavailable as exc:
            parser.error(str(exc))

        pred_ids = _prediction_ids(predictions_path)
        grade_ids = _ungraded_ids(work_dir, args.run_id, model_name, pred_ids)
        logger.info(
            "Predictions=%d already_graded=%d to_grade=%d "
            "(prepull=%s sequential=%s remove_after=%s)",
            len(pred_ids),
            len(pred_ids) - len(grade_ids),
            len(grade_ids),
            prepull,
            args.sequential,
            remove_after,
        )
        _run_harness_with_image_lifecycle(
            predictions_path=predictions_path,
            run_meta=run_meta,
            run_id=args.run_id,
            work_dir=work_dir,
            grade_ids=grade_ids,
            max_workers=args.max_workers,
            timeout=args.timeout,
            cache_level=args.cache_level,
            namespace=namespace,
            prepull=prepull,
            sequential=args.sequential,
            remove_after=remove_after,
        )

    aggregate_path = report_path(work_dir, model_name, args.run_id)
    aggregate = load_report(aggregate_path) if aggregate_path.exists() else None
    if aggregate is None:
        logger.warning("No aggregate harness report at %s", aggregate_path)

    summary = build_summary(
        run_dir=run_dir,
        work_dir=work_dir,
        run_id=args.run_id,
        run_meta=run_meta,
        suite=suite,
        aggregate=aggregate,
    )

    out = run_dir / "summary.json"
    with open(out, "w") as f:
        json.dump(summary, f, indent=2)

    print_summary(summary)
    print(f"\nSummary written to {out}")
    print(f"Next: python -m src.evaluation.analyze --run_dir {run_dir}")


if __name__ == "__main__":
    main()
