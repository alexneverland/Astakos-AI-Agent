"""Offline end-to-end timing tests with synthetic time and model responses."""
import asyncio
import json
from uuid import uuid4

import pytest


@pytest.fixture
def timing_env(monkeypatch, tmp_path):
    """Keep diagnostics and all transport in an isolated offline boundary."""
    import socket
    import memory.execution_trace as traces
    from services import turn_timing as timing

    original_connect = socket.socket.connect

    def reject(sock, address):
        # Windows asyncio creates a loopback socketpair for its wakeup pipe.
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        raise AssertionError("outbound transport is forbidden")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(traces, "_TRACES_DIR", str(tmp_path / "traces"))
    clock = [10.0]
    monkeypatch.setattr(timing.time, "monotonic", lambda: clock[0])
    return timing, traces, clock


def test_includes_pregraph_model_retry_and_final_delivery(timing_env):
    timing, traces, clock = timing_env
    callback = timing.ModelTimingCallback("demo", "demo-model")

    @timing.trace_stage("routine_feedback")
    def feedback():
        run = uuid4()
        callback.on_chat_model_start({}, [["PRIVATE PROMPT"]], run_id=run)
        clock[0] += 180
        callback.on_llm_error(RuntimeError("PRIVATE ERROR"), run_id=run)
        with timing.timing_span("retry_backoff"):
            clock[0] += 2
        run = uuid4()
        callback.on_chat_model_start({}, [], run_id=run)
        clock[0] += 5
        callback.on_llm_end("PRIVATE ANSWER", run_id=run)

    @timing.trace_turn("web")
    def turn():
        feedback()
        trace = traces.ExecutionTrace("web", "synthetic project reply", console=False)
        clock[0] += 20
        trace.finalize(response="done")
        trace.save()
        clock[0] += 1
        return "done"

    assert turn() == "done"
    rows = traces.load_traces()
    assert len(rows) == 1
    row = rows[0]
    assert row["duration_ms"] == 208000
    assert row["latency"]["model_wall_ms"] == 185000
    spans = row["latency"]["spans"]
    assert [s["duration_ms"] for s in spans if s["kind"] == "model"] == [180000, 5000]
    assert next(s for s in spans if s["name"] == "routine_feedback")["duration_ms"] == 187000
    assert row["latency"]["uncovered_ms"] == 21000
    assert "PRIVATE" not in json.dumps(row)
    assert timing.current_timing() is None


def test_async_worker_isolation_early_return_and_failure(timing_env):
    timing, traces, clock = timing_env

    @timing.trace_turn("telegram")
    async def turn(fail):
        @timing.trace_stage("worker")
        def worker():
            return timing.current_timing().trace_id
        identity = await asyncio.to_thread(worker)
        await asyncio.sleep(0)
        if fail:
            raise ValueError("PRIVATE ERROR")
        return identity

    async def exercise():
        return await asyncio.gather(turn(False), turn(True), return_exceptions=True)

    results = asyncio.run(exercise())
    assert isinstance(results[1], ValueError)
    rows = traces.load_traces()
    assert len(rows) == 2
    assert len({row["trace_id"] for row in rows}) == 2
    assert results[0] in {row["trace_id"] for row in rows}
    assert {row["error"] for row in rows} == {None, "ValueError"}
    assert all(len(row["latency"]["spans"]) == 1 for row in rows)
    assert timing.current_timing() is None


def test_nested_model_spans_count_union_and_closed_context_ignores_late_work(timing_env):
    timing, traces, clock = timing_env
    saved = []

    @timing.trace_turn("matrix")
    def turn():
        saved.append(timing.current_timing())
        with timing.timing_span("outer", kind="model"):
            clock[0] += 1
            with timing.timing_span("inner", kind="model"):
                clock[0] += 2
            clock[0] += 1

    turn()
    row = traces.load_traces()[0]
    assert row["latency"]["model_wall_ms"] == 4000
    assert row["latency"]["uncovered_ms"] == 0
    assert saved[0].closed


def test_real_langchain_direct_and_bound_calls_emit_model_timings(timing_env):
    """Exercise actual callback dispatch without contacting a provider."""
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    timing, traces, clock = timing_env
    model = FakeListChatModel(responses=["first", "second"],
        callbacks=[timing.ModelTimingCallback("offline", "fake-chat")])

    @timing.trace_turn("web")
    def turn():
        assert model.invoke("synthetic request").content == "first"
        assert model.bind(temperature=0).invoke("synthetic request").content == "second"

    turn()
    spans = traces.load_traces()[0]["latency"]["spans"]
    assert len(spans) == 2
    assert all(s["kind"] == "model" and s["model"] == "fake-chat" for s in spans)


def test_langgraph_worker_propagates_stage_and_callback_context(timing_env):
    """Use LangGraph's actual worker executor rather than a mocked graph."""
    from langgraph.graph import StateGraph, START, END
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    timing, traces, clock = timing_env
    model = FakeListChatModel(responses=["done"],
        callbacks=[timing.ModelTimingCallback("offline", "fake-chat")])

    @timing.trace_stage("graph.demo")
    def node(state: dict) -> dict:
        clock[0] += 1
        return {"answer": model.invoke("synthetic request").content}

    builder = StateGraph(dict)
    builder.add_node("demo", node)
    builder.add_edge(START, "demo")
    builder.add_edge("demo", END)
    graph = builder.compile()

    @timing.trace_turn("web")
    def turn():
        return graph.invoke({})

    assert turn()["answer"] == "done"
    spans = traces.load_traces()[0]["latency"]["spans"]
    assert {s["name"] for s in spans} == {"model_call", "graph.demo"}
    assert next(s for s in spans if s["kind"] == "model")["stage"] == "graph.demo"


def test_closed_inherited_context_and_failed_sink_do_not_change_results(timing_env, monkeypatch):
    from contextvars import copy_context
    timing, traces, clock = timing_env
    contexts = []

    @timing.trace_turn("web")
    def turn():
        contexts.append(copy_context())
        return "unchanged"

    def bad_save(self):
        raise OSError("PRIVATE PATH")

    monkeypatch.setattr(traces.ExecutionTrace, "save", bad_save)
    assert turn() == "unchanged"
    assert contexts[0].run(timing.current_timing) is None
    assert timing.current_timing() is None


@pytest.mark.parametrize("path", ["safe_llm", "adapter", "helper"])
def test_application_retries_record_failed_attempt_and_actual_backoff(timing_env, monkeypatch, path):
    """Exercise the production retry loops with only their transport replaced."""
    from types import SimpleNamespace
    import core.brain as brain
    import services.gemini as gemini
    timing, traces, clock = timing_env
    attempts = []

    def invoke(*args, **kwargs):
        attempts.append(1)
        clock[0] += 3
        if len(attempts) == 1:
            raise TimeoutError("timeout PRIVATE ERROR")
        return SimpleNamespace(content="synthetic answer")

    def sleep(seconds):
        clock[0] += seconds

    monkeypatch.setattr(brain.time, "sleep", sleep)
    monkeypatch.setattr(gemini, "llm", SimpleNamespace(invoke=invoke))

    @timing.trace_turn("web")
    def turn():
        if path == "safe_llm":
            return brain.safe_llm_invoke(SimpleNamespace(invoke=invoke), "synthetic")
        if path == "adapter":
            return brain.safe_adapter_call(invoke)
        return gemini.safe_gemini_call("synthetic")

    result = turn()
    assert getattr(result, "content", None) == "synthetic answer"
    row = traces.load_traces()[0]
    spans = row["latency"]["spans"]
    assert len(attempts) == 2
    assert row["duration_ms"] == 8000
    assert row["latency"]["retry_wait_wall_ms"] == 2000
    assert [s["attempt"] for s in spans if s["kind"] == "attempt"] == [1, 2]
    assert [s["error"] for s in spans if s["kind"] == "attempt"] == ["TimeoutError", None]
    assert "PRIVATE" not in json.dumps(row)


def test_native_provider_operation_includes_sdk_time_without_retaining_input(timing_env, monkeypatch):
    from core.ai_provider import OpenAIAdapter
    from types import SimpleNamespace
    timing, traces, clock = timing_env
    adapter = OpenAIAdapter(api_key="synthetic-unused")

    def invoke(messages):
        clock[0] += 4
        return SimpleNamespace(content="done")

    monkeypatch.setattr(adapter, "_get_llm", lambda **kwargs: SimpleNamespace(invoke=invoke))

    @timing.trace_turn("web")
    def turn():
        return adapter.generate_text("PRIVATE PROMPT")

    assert turn() == "done"
    row = traces.load_traces()[0]
    assert row["latency"]["model_wall_ms"] == 4000
    assert row["latency"]["spans"][0]["provider"] == "openai"
    assert "PRIVATE" not in json.dumps(row)
