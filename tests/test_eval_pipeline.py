"""Offline tests for the scoring/analysis join. No Docker, no LLM, no repos."""

import json

from src.evaluation.analyze import analyze, classify_failure
from src.evaluation.run_eval import (
    OUTCOME_APPLY_FAILED,
    OUTCOME_NO_PATCH,
    OUTCOME_REGRESSION,
    OUTCOME_RESOLVED,
    OUTCOME_TESTS_FAILED,
    build_summary,
    classify_outcome,
)

# --- outcome classification -------------------------------------------------


def test_resolved():
    assert classify_outcome({}, {"resolved": True}) == OUTCOME_RESOLVED


def test_apply_failed():
    grading = {"resolved": False, "patch_exists": True, "patch_successfully_applied": False}
    assert classify_outcome({}, grading) == OUTCOME_APPLY_FAILED


def test_regression_when_target_passes_but_others_break():
    grading = {
        "resolved": False,
        "patch_exists": True,
        "patch_successfully_applied": True,
        "tests_status": {
            "FAIL_TO_PASS": {"success": ["t1"], "failure": []},
            "PASS_TO_PASS": {"success": [], "failure": ["t2"]},
        },
    }
    assert classify_outcome({}, grading) == OUTCOME_REGRESSION


def test_tests_failed_when_target_still_fails():
    grading = {
        "resolved": False,
        "patch_exists": True,
        "patch_successfully_applied": True,
        "tests_status": {
            "FAIL_TO_PASS": {"success": [], "failure": ["t1"]},
            "PASS_TO_PASS": {"success": ["t2"], "failure": []},
        },
    }
    assert classify_outcome({}, grading) == OUTCOME_TESTS_FAILED


def test_no_patch_without_grading():
    assert classify_outcome({"model_patch": ""}, None) == OUTCOME_NO_PATCH


# --- failure buckets --------------------------------------------------------


def test_explored_without_editing():
    case = {
        "outcome": "no_patch",
        "stop_reason": "max_rounds",
        "tool_calls": {"bash": 40, "read_file": 20},
        "tool_errors": {},
        "patch_files": [],
    }
    assert classify_failure(case) == "explored_without_editing"


def test_gave_up_early():
    case = {
        "outcome": "no_patch",
        "stop_reason": "end_turn",
        "tool_calls": {"bash": 3},
        "tool_errors": {},
        "patch_files": [],
    }
    assert classify_failure(case) == "gave_up_early"


def test_edit_tool_dead_end_when_every_edit_failed():
    case = {
        "outcome": "no_patch",
        "stop_reason": "max_rounds",
        "tool_calls": {"edit_file": 6, "bash": 10},
        "tool_errors": {"edit_file": 6},
        "patch_files": [],
    }
    assert classify_failure(case) == "edit_tool_dead_end"


def test_wrong_location_when_patch_misses_gold_files():
    case = {
        "outcome": "tests_failed",
        "stop_reason": "end_turn",
        "tool_calls": {"edit_file": 1},
        "tool_errors": {},
        "patch_files": ["src/unrelated.py"],
        "gold_files": ["src/target.py"],
    }
    assert classify_failure(case) == "wrong_location"


def test_right_file_wrong_fix_when_patch_overlaps_gold():
    case = {
        "outcome": "tests_failed",
        "stop_reason": "end_turn",
        "tool_calls": {"edit_file": 1},
        "tool_errors": {},
        "patch_files": ["src/target.py"],
        "gold_files": ["src/target.py"],
    }
    assert classify_failure(case) == "right_file_wrong_fix"


def test_infra_buckets_are_separated_from_agent_failures():
    assert classify_failure({"run_status": "setup_error", "outcome": None}) == "infra_setup"
    assert classify_failure({"stop_reason": "error", "outcome": None}) == "infra_api"


# --- end-to-end join -------------------------------------------------------


def _write_run(tmp_path, *, instance_id, status, patch, attempts):
    run_dir = tmp_path / "run"
    log_dir = run_dir / "logs" / instance_id
    log_dir.mkdir(parents=True)
    (log_dir / "result.json").write_text(json.dumps({
        "instance_id": instance_id,
        "repo": "acme/widget",
        "status": status,
        "model_patch": patch,
        "patch_stats": {"files": ["src/target.py"]} if patch else {},
        "gate": {"passed": bool(patch), "reason": "ok" if patch else "empty patch"},
        "attempts": attempts,
        "usage_total": {"total_tokens": 12345},
        "duration_s": 42.0,
    }))
    (run_dir / "run_meta.json").write_text(json.dumps({
        "dataset": "princeton-nlp/SWE-bench_Verified",
        "split": "test",
        "model_name": "my-agent",
        "suite": "suite_test",
        "predictions_file": "my-agent__SWE-bench_Verified__test.jsonl",
        "max_rounds": 30,
        "instance_ids": [instance_id],
    }))
    return run_dir


def test_summary_join_uses_suite_metadata(tmp_path):
    iid = "acme__widget-1"
    run_dir = _write_run(
        tmp_path,
        instance_id=iid,
        status="patch_written",
        patch="diff --git a/src/target.py b/src/target.py\n@@\n+x",
        attempts=[{
            "attempt": 1, "stop_reason": "end_turn", "rounds": 12,
            "tool_calls": {"bash": 5, "edit_file": 1}, "tool_errors": {},
            "had_successful_edit": True, "usage": {"total_tokens": 12345},
        }],
    )
    suite = {
        "name": "suite_test",
        "cases": [{
            "instance_id": iid, "repo": "acme/widget", "tier": "T2",
            "difficulty": "15 min - 1 hour", "problem_type": "crash",
            "gold_files": ["src/target.py"], "gold_n_files": 1,
        }],
        "size": 1,
    }
    summary = build_summary(
        run_dir=run_dir,
        work_dir=run_dir / "harness",   # no harness output present
        run_id="t1",
        run_meta=json.loads((run_dir / "run_meta.json").read_text()),
        suite=suite,
        aggregate=None,
    )
    assert summary["total"] == 1
    case = summary["cases"][0]
    # Suite metadata is joined in even though the harness produced nothing.
    assert case["tier"] == "T2"
    assert case["problem_type"] == "crash"
    assert case["gold_files"] == ["src/target.py"]
    assert case["stop_reason"] == "end_turn"
    assert case["rounds"] == 12
    assert case["tokens"] == 12345
    assert summary["by_tier"]["T2"]["total"] == 1


def test_analyze_falls_back_to_result_json_without_summary(tmp_path):
    iid = "acme__widget-2"
    run_dir = _write_run(
        tmp_path,
        instance_id=iid,
        status="empty_patch",
        patch="",
        attempts=[{
            "attempt": 1, "stop_reason": "max_rounds", "rounds": 30,
            "tool_calls": {"bash": 48, "read_file": 33}, "tool_errors": {},
            "had_successful_edit": False, "usage": {"total_tokens": 999},
        }],
    )
    report = analyze(run_dir)
    assert report["graded"] is False
    assert report["total"] == 1
    assert "explored_without_editing" in report["buckets"]
    assert report["buckets"]["explored_without_editing"]["instance_ids"] == [iid]


def test_analyze_reads_event_signals(tmp_path):
    iid = "acme__widget-3"
    run_dir = _write_run(
        tmp_path,
        instance_id=iid,
        status="empty_patch",
        patch="",
        attempts=[{
            "attempt": 1, "stop_reason": "max_rounds", "rounds": 30,
            "tool_calls": {"bash": 2}, "tool_errors": {},
            "had_successful_edit": False, "usage": {},
        }],
    )
    attempt = run_dir / "logs" / iid / "attempt_1"
    attempt.mkdir()
    events = [
        {"data": {"event": "llm_call", "turn": 1, "usage": {"input_tokens": 5000}}},
        {"data": {"event": "tool_start", "tool_name": "bash",
                  "args": {"command": "python -m pytest tests/test_a.py"}}},
        {"data": {"event": "tool_start", "tool_name": "bash",
                  "args": {"command": "ls -la"}}},
        {"data": {"event": "tool_start", "tool_name": "read_file", "args": {"path": "a.py"}}},
        {"data": {"event": "llm_call", "turn": 2, "usage": {"input_tokens": 41000}}},
    ]
    (attempt / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n"
    )

    report = analyze(run_dir)
    signals = report["cases"][0]["signals"]
    assert signals["bash_calls"] == 2
    assert signals["read_calls"] == 1
    assert signals["ran_tests"] is True
    assert signals["max_input_tokens"] == 41000


def test_instance_image_name_matches_swebench_prebuilt_tag():
    from src.evaluation.evaluator import instance_image_name

    assert instance_image_name("pallets__flask-5014") == (
        "swebench/sweb.eval.x86_64.pallets_1776_flask-5014:latest"
    )
    assert instance_image_name("scikit-learn__scikit-learn-25102") == (
        "swebench/sweb.eval.x86_64.scikit-learn_1776_scikit-learn-25102:latest"
    )
