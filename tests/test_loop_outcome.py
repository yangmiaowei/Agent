"""Offline tests for loop mechanics: no LLM calls, no repos."""

from types import SimpleNamespace

from src.evaluation.agent_loop import FORCE_EDIT_NUDGE, SweBenchLoop
from src.model.usage import Usage
from src.orchestrator.base_loop import BaseLoop
from src.orchestrator.outcome import STOP_END_TURN, STOP_ERROR, STOP_MAX_ROUNDS


class FakeBlock(SimpleNamespace):
    def model_dump(self):
        return {"type": self.type, **{k: v for k, v in self.__dict__.items() if k != "type"}}


def text_block(text="ok"):
    return FakeBlock(type="text", text=text)


def tool_block(name, tool_id="t1", **inp):
    return FakeBlock(type="tool_use", name=name, id=tool_id, input=inp)


class FakeAgent:
    """Replays a scripted list of (stop_reason, blocks) responses."""

    def __init__(self, script, *, raise_on_turn=None):
        self.script = list(script)
        self.raise_on_turn = raise_on_turn
        self.turn = 0
        self.last_usage = Usage()

    def run(self, messages, tools=None, system=None):
        self.turn += 1
        if self.raise_on_turn == self.turn:
            raise RuntimeError("boom")
        stop_reason, blocks = self.script[min(self.turn - 1, len(self.script) - 1)]
        self.last_usage = Usage(calls=1, input_tokens=100, output_tokens=10)
        return SimpleNamespace(stop_reason=stop_reason, content=blocks)


class FakeRuntime:
    def resolve(self, ctx):
        self.last_mode = ctx.mode
        return SimpleNamespace(tool_view=SimpleNamespace(list_tools=lambda: []), system_prompt="sys")


class FakeExecutor:
    def __init__(self, outputs=None):
        self.outputs = outputs or {}
        self.calls = []

    def run(self, name, args, ctx, tool_view):
        self.calls.append(name)
        return self.outputs.get(name, f"ran {name}")


def build(script, *, loop_cls=BaseLoop, outputs=None, raise_on_turn=None, **kw):
    agent = FakeAgent(script, raise_on_turn=raise_on_turn)
    runtime = FakeRuntime()
    executor = FakeExecutor(outputs)
    loop = loop_cls(agent=agent, runtime=runtime, executor=executor, **kw)
    return loop, agent, runtime, executor


def test_end_turn_reports_outcome():
    loop, *_ = build([("end_turn", [text_block()])])
    out = loop.loop([{"role": "user", "content": "hi"}])
    assert out.stop_reason == STOP_END_TURN
    assert out.rounds == 1
    assert out.usage["calls"] == 1
    assert out.usage["input_tokens"] == 100


def test_max_rounds_is_reported_not_silent():
    loop, _, _, executor = build([("tool_use", [tool_block("bash")])])
    out = loop.loop([{"role": "user", "content": "hi"}], max_rounds=3)
    assert out.stop_reason == STOP_MAX_ROUNDS
    assert out.rounds == 3
    assert out.tool_calls == {"bash": 3}
    assert out.usage["calls"] == 3
    assert executor.calls == ["bash"] * 3


def test_llm_error_is_reported():
    loop, *_ = build([("tool_use", [tool_block("bash")])], raise_on_turn=2)
    out = loop.loop([{"role": "user", "content": "hi"}], max_rounds=5)
    assert out.stop_reason == STOP_ERROR
    assert "RuntimeError: boom" in out.error
    assert out.rounds == 1


def test_tool_errors_counted():
    loop, *_ = build(
        [("tool_use", [tool_block("edit_file")]), ("end_turn", [text_block()])],
        outputs={"edit_file": "Error: Text not found in a.py"},
    )
    out = loop.loop([{"role": "user", "content": "hi"}], max_rounds=5)
    assert out.tool_errors == {"edit_file": 1}
    assert out.tool_calls == {"edit_file": 1}


def test_swe_loop_uses_swe_mode():
    loop, _, runtime, _ = build([("end_turn", [text_block()])], loop_cls=SweBenchLoop)
    loop.loop([{"role": "user", "content": "hi"}])
    assert runtime.last_mode == "swe"


def test_swe_loop_nudges_when_no_edit():
    loop, *_ = build(
        [("tool_use", [tool_block("bash")])],
        loop_cls=SweBenchLoop,
        nudge_before_last_rounds=2,
    )
    messages = [{"role": "user", "content": "hi"}]
    loop.loop(messages, max_rounds=4)
    assert any(m.get("content") == FORCE_EDIT_NUDGE for m in messages)


def test_swe_loop_failed_edit_still_nudges():
    """A failed edit_file must not count as having edited."""
    loop, *_ = build(
        [("tool_use", [tool_block("edit_file")])],
        loop_cls=SweBenchLoop,
        outputs={"edit_file": "Error: Text not found in a.py"},
        nudge_before_last_rounds=2,
    )
    messages = [{"role": "user", "content": "hi"}]
    loop.loop(messages, max_rounds=4)
    assert loop.has_edited is False
    assert any(m.get("content") == FORCE_EDIT_NUDGE for m in messages)


def test_swe_loop_successful_edit_suppresses_nudge():
    loop, *_ = build(
        [("tool_use", [tool_block("edit_file")])],
        loop_cls=SweBenchLoop,
        outputs={"edit_file": "Edited a.py"},
        nudge_before_last_rounds=2,
    )
    messages = [{"role": "user", "content": "hi"}]
    loop.loop(messages, max_rounds=4)
    assert loop.has_edited is True
    assert not any(m.get("content") == FORCE_EDIT_NUDGE for m in messages)


def test_events_logged_include_loop_end_and_usage():
    class Rec:
        def __init__(self):
            self.events = []

        def log(self, data):
            self.events.append(data)

    rec = Rec()
    loop, *_ = build([("end_turn", [text_block()])])
    loop.loop([{"role": "user", "content": "hi"}], logger=rec)
    kinds = [e.get("event") for e in rec.events if isinstance(e, dict)]
    assert "llm_call" in kinds
    assert "loop_end" in kinds
