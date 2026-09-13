#!/usr/bin/env python3
"""Bucket failures by root cause and point at the capability to fix.

Auto-labels every unresolved case so the manual review starts from a grouped
list rather than 24 raw event logs. Each bucket names the agent capability it
implicates, because the point of the run is deciding what to change next.

Works with or without harness grading: with `summary.json` it can separate
"patched the wrong file" from "patched the right file badly"; without it, it
still reports the agent-side failures (no patch, rounds exhausted, edit tool
dead ends) from `result.json` alone.

Example:
    python -m src.evaluation.analyze --run_dir predictions
"""

import json
import logging
from argparse import ArgumentParser
from collections import Counter, defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

RESOLVED = "resolved"

# Bucket -> (human description, implicated capability).
BUCKETS: dict[str, tuple[str, str]] = {
    "infra_setup": (
        "repo clone/checkout failed; the agent never ran",
        "infrastructure (not the agent)",
    ),
    "infra_api": (
        "LLM call failed after retries",
        "infrastructure (not the agent)",
    ),
    "explored_without_editing": (
        "burned every round on exploration and never landed an edit",
        "search/navigation efficiency + stopping policy",
    ),
    "gave_up_early": (
        "ended its turn without producing a patch, with rounds left",
        "task framing / persistence in the prompt",
    ),
    "edit_tool_dead_end": (
        "edit_file kept failing to match, so edits never applied",
        "edit tool ergonomics (exact-match-only replace)",
    ),
    "gate_rejected": (
        "produced a patch our own quality gate refused",
        "patch gate rules, or the agent editing only tests",
    ),
    "apply_failed": (
        "patch was malformed and the harness could not apply it",
        "diff generation / workspace hygiene",
    ),
    "wrong_location": (
        "patched files that the reference fix does not touch",
        "fault localisation",
    ),
    "right_file_wrong_fix": (
        "found the right file but the fix does not satisfy the tests",
        "reasoning about the fix + verifying against tests",
    ),
    "regression": (
        "target tests pass but previously passing tests broke",
        "change scoping / regression checking",
    ),
    "rounds_exhausted": (
        "hit the round limit with a patch that was not good enough",
        "round budget or exploration efficiency",
    ),
    "unknown": ("not classified", "needs manual review"),
}

TEST_COMMAND_HINTS = ("pytest", "tox", "runtests", "unittest", "nose", "python -m test")


def _read_json(path: Path):
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def scan_events(attempt_dir: Path) -> dict:
    """Extract behavioural signals from one attempt's event log."""
    signals = {
        "bash_calls": 0,
        "read_calls": 0,
        "edit_calls": 0,
        "ran_tests": False,
        "repeated_edit_failures": 0,
        "max_input_tokens": 0,
    }
    events_file = attempt_dir / "events.jsonl"
    if not events_file.exists():
        return signals

    failed_edit_targets: Counter = Counter()
    with open(events_file) as f:
        for line in f:
            if not line.strip():
                continue
            try:
                data = json.loads(line).get("data") or {}
            except json.JSONDecodeError:
                continue

            if data.get("event") == "llm_call":
                usage = data.get("usage") or {}
                signals["max_input_tokens"] = max(
                    signals["max_input_tokens"], usage.get("input_tokens", 0)
                )
                continue

            if data.get("event") == "tool_start":
                name = data.get("tool_name")
                args = data.get("args") or {}
                if name == "bash":
                    signals["bash_calls"] += 1
                    command = str(args.get("command", ""))
                    if any(hint in command for hint in TEST_COMMAND_HINTS):
                        signals["ran_tests"] = True
                elif name == "read_file":
                    signals["read_calls"] += 1
                elif name == "edit_file":
                    signals["edit_calls"] += 1
                continue

            if data.get("event") == "tool_end" and data.get("tool_name") == "edit_file":
                output = str(data.get("output", ""))
                if output.startswith("Error"):
                    failed_edit_targets[output[:120]] += 1

    signals["repeated_edit_failures"] = sum(
        count for count in failed_edit_targets.values() if count > 1
    )
    return signals


def classify_failure(case: dict) -> str:
    """Pick the most actionable root cause. Order matters: infrastructure first,
    then agent-side causes, then patch-quality causes."""
    outcome = case.get("outcome")
    if outcome == RESOLVED:
        return RESOLVED

    status = case.get("run_status")
    stop = case.get("stop_reason")

    if status == "setup_error":
        return "infra_setup"
    if stop == "error":
        return "infra_api"

    tool_calls = case.get("tool_calls") or {}
    tool_errors = case.get("tool_errors") or {}
    edit_attempts = tool_calls.get("edit_file", 0)
    edit_failures = tool_errors.get("edit_file", 0)
    has_patch = bool(case.get("patch_files"))

    # No usable patch at all: distinguish *why* the agent produced nothing.
    if outcome in ("no_patch", None) and not has_patch:
        if edit_attempts and edit_failures == edit_attempts:
            return "edit_tool_dead_end"
        if stop == "max_rounds":
            return "explored_without_editing"
        if stop == "end_turn":
            return "gave_up_early"

    if status == "gate_rejected" or outcome == "gate_rejected":
        return "gate_rejected"
    if outcome == "apply_failed":
        return "apply_failed"
    if outcome == "regression":
        return "regression"

    if outcome == "tests_failed":
        gold = set(case.get("gold_files") or [])
        patched = set(case.get("patch_files") or [])
        if gold and patched and not (gold & patched):
            return "wrong_location"
        return "right_file_wrong_fix"

    if stop == "max_rounds":
        return "rounds_exhausted"
    return "unknown"


def load_cases(run_dir: Path) -> tuple[list[dict], bool]:
    """Prefer summary.json (has harness grading); fall back to result.json files."""
    summary = _read_json(run_dir / "summary.json")
    if summary and summary.get("cases"):
        return summary["cases"], True

    logger.warning(
        "No summary.json in %s; analysing agent-side signals only. "
        "Run `python -m src.evaluation.analyze` again after run_eval to get "
        "fault-localisation and test-failure buckets.",
        run_dir,
    )
    cases = []
    logs_dir = run_dir / "logs"
    for result_file in sorted(logs_dir.glob("*/result.json")):
        result = _read_json(result_file)
        if not result:
            continue
        attempts = result.get("attempts") or []
        last = attempts[-1] if attempts else {}
        cases.append({
            "instance_id": result["instance_id"],
            "repo": result.get("repo"),
            "tier": None,
            "problem_type": None,
            "outcome": "no_patch" if not (result.get("model_patch") or "").strip() else None,
            "run_status": result.get("status"),
            "stop_reason": last.get("stop_reason"),
            "rounds": last.get("rounds"),
            "attempts": len(attempts),
            "tool_calls": last.get("tool_calls") or {},
            "tool_errors": last.get("tool_errors") or {},
            "gate_reason": (result.get("gate") or {}).get("reason"),
            "tokens": (result.get("usage_total") or {}).get("total_tokens"),
            "duration_s": result.get("duration_s"),
            "patch_files": (result.get("patch_stats") or {}).get("files", []),
            "gold_files": [],
        })
    return cases, False


def analyze(run_dir: Path) -> dict:
    cases, graded = load_cases(run_dir)
    if not cases:
        raise SystemExit(f"No cases found under {run_dir}")

    for case in cases:
        case["failure_bucket"] = classify_failure(case)
        instance_log_dir = run_dir / "logs" / case["instance_id"]
        attempt_dirs = sorted(instance_log_dir.glob("attempt_*"))
        case["signals"] = scan_events(attempt_dirs[-1]) if attempt_dirs else {}

    buckets: dict[str, list[dict]] = defaultdict(list)
    for case in cases:
        buckets[case["failure_bucket"]].append(case)

    return {
        "run_dir": str(run_dir),
        "graded": graded,
        "total": len(cases),
        "resolved": len(buckets.get(RESOLVED, [])),
        "buckets": {
            name: {
                "count": len(group),
                "description": BUCKETS.get(name, ("", ""))[0],
                "capability": BUCKETS.get(name, ("", ""))[1],
                "instance_ids": [c["instance_id"] for c in group],
            }
            for name, group in sorted(buckets.items(), key=lambda kv: -len(kv[1]))
            if name != RESOLVED
        },
        "cases": cases,
    }


def print_report(report: dict) -> None:
    total = report["total"]
    print(f"\n=== Failure analysis: {report['resolved']}/{total} resolved ===")
    if not report["graded"]:
        print("(agent-side signals only; no harness grading available)")

    print("\nFailure buckets:")
    for name, info in report["buckets"].items():
        print(f"\n  {name}  x{info['count']}")
        print(f"    what     : {info['description']}")
        print(f"    fix what : {info['capability']}")
        for iid in info["instance_ids"]:
            print(f"      - {iid}")

    cases = report["cases"]
    unresolved = [c for c in cases if c["failure_bucket"] != RESOLVED]

    print("\nExploration efficiency (unresolved cases):")
    print(f'  {"instance_id":42} {"bash":>5} {"read":>5} {"edit":>5} '
          f'{"tests?":>7} {"rnd":>4} {"tokens":>9}')
    for c in sorted(unresolved, key=lambda c: c["instance_id"]):
        s = c.get("signals") or {}
        print(f'  {c["instance_id"]:42} {s.get("bash_calls", 0):5} '
              f'{s.get("read_calls", 0):5} {s.get("edit_calls", 0):5} '
              f'{"yes" if s.get("ran_tests") else "no":>7} '
              f'{c.get("rounds") if c.get("rounds") is not None else "-":>4} '
              f'{c.get("tokens") or 0:9,}')

    ran_tests = sum(1 for c in cases if (c.get("signals") or {}).get("ran_tests"))
    print(f"\nCases where the agent ran the test suite at least once: "
          f"{ran_tests}/{total}")

    tier_buckets: dict[str, Counter] = defaultdict(Counter)
    if any(c.get("tier") for c in cases):
        for c in cases:
            tier_buckets[c.get("tier") or "?"][c["failure_bucket"]] += 1
        print("\nBuckets by difficulty tier:")
        for tier in sorted(tier_buckets):
            items = ", ".join(f"{k}={v}" for k, v in tier_buckets[tier].most_common())
            print(f"  {tier}: {items}")


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--run_dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None,
                        help="Defaults to <run_dir>/analysis.json")
    args = parser.parse_args()

    report = analyze(args.run_dir.resolve())
    out = args.out or args.run_dir / "analysis.json"
    with open(out, "w") as f:
        json.dump(report, f, indent=2)

    print_report(report)
    print(f"\nAnalysis written to {out}")


if __name__ == "__main__":
    main()
