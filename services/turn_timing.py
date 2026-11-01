"""Bounded, content-free latency spans sharing the native execution trace sink."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from functools import wraps
import inspect
import json
import threading
import time
from typing import Any, Callable, Iterator
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackHandler

_active: ContextVar[TurnTiming | None] = ContextVar("astakos_turn_timing", default=None)
_stage: ContextVar[str] = ContextVar("astakos_timing_stage", default="turn")
_MAX_SPANS = 512


def _union_ms(spans: list[dict[str, Any]]) -> int:
    """Measure covered wall time without summing nested or concurrent spans."""
    end = 0
    total = 0
    for span in sorted(spans, key=lambda item: item["start_ms"]):
        start, stop = span["start_ms"], span["start_ms"] + span["duration_ms"]
        total += max(0, stop - max(start, end))
        end = max(end, stop)
    return total


class TurnTiming:
    """One handler's timing context; workers may share it but other turns cannot."""

    def __init__(self, channel: str) -> None:
        self.channel = channel
        self.trace_id = str(uuid4())[:8]
        self.start = time.monotonic()
        self.timestamp = datetime.now().isoformat(timespec="seconds")
        self.spans: list[dict[str, Any]] = []
        self.trace: Any = None
        self.closed = False
        self.dropped = 0
        self._lock = threading.RLock()
        self.emit("latency_started")

    def emit(self, event: str, **fields: Any) -> None:
        """Emit only timing metadata, never request bodies or exception messages."""
        try:
            print("[LatencyTrace]: " + json.dumps({
                "event": event, "channel": self.channel, "trace_id": self.trace_id,
                "elapsed_ms": max(0, round((time.monotonic() - self.start) * 1000)),
                **fields,
            }), flush=True)
        except (OSError, UnicodeError, ValueError):
            pass

    def record(self, name: str, started: float, *, kind: str = "stage",
               error: str | None = None, **metadata: Any) -> None:
        """Append an allowlisted span, ignoring late inherited background work."""
        with self._lock:
            if self.closed:
                return
            if len(self.spans) >= _MAX_SPANS:
                self.dropped += 1
                return
            span = {"name": name, "kind": kind,
                    "start_ms": max(0, round((started - self.start) * 1000)),
                    "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
                    "error": error}
            span.update({key: value for key, value in metadata.items()
                         if key in {"provider", "model", "stage", "attempt", "call_id"}})
            self.spans.append(span)
            self.emit("latency_span", **span)

    def finish(self, error: BaseException | None) -> None:
        """Persist exactly once, after the handler including final delivery returns."""
        from memory.execution_trace import ExecutionTrace

        with self._lock:
            duration = max(0, round((time.monotonic() - self.start) * 1000))
            trace = self.trace
            created = trace is None
            if trace is None:
                trace = ExecutionTrace(self.channel, "", console=False)
            self.closed = True
            if created:
                trace.finalize(error=type(error).__name__ if error else None)
            elif error is not None and not trace.error:
                trace.finalize(error=type(error).__name__)
            trace.duration_ms = duration
            trace.latency = {
                "total_ms": duration,
                "model_wall_ms": _union_ms([s for s in self.spans if s["kind"] == "model"]),
                "retry_wait_wall_ms": _union_ms([s for s in self.spans if s["kind"] == "retry_wait"]),
                "uncovered_ms": max(0, duration - _union_ms(self.spans)),
                "spans": list(self.spans), "dropped_spans": self.dropped,
            }
            self.emit("latency_finished", total_ms=duration,
                      model_wall_ms=trace.latency["model_wall_ms"],
                      uncovered_ms=trace.latency["uncovered_ms"])
            trace.save()


def current_timing() -> TurnTiming | None:
    """Return this context's active turn, excluding already closed collectors."""
    timing = _active.get()
    return timing if timing is not None and not timing.closed else None


@contextmanager
def timing_span(name: str, *, kind: str = "stage", **metadata: Any) -> Iterator[None]:
    """Measure success and failure while preserving the original exception."""
    timing = current_timing()
    if timing is None:
        yield
        return
    parent = _stage.get()
    token = _stage.set(name if parent == "turn" else parent + "." + name)
    started = time.monotonic()
    timing.emit("latency_stage_started", name=name, kind=kind)
    error = None
    try:
        yield
    except BaseException as exc:
        error = type(exc).__name__
        raise
    finally:
        timing.record(name, started, kind=kind, error=error, **metadata)
        _stage.reset(token)


def trace_stage(name: str) -> Callable:
    """Wrap a synchronous or asynchronous stage without altering its signature."""
    def decorate(func: Callable) -> Callable:
        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapped(*args: Any, **kwargs: Any) -> Any:
                with timing_span(name):
                    return await func(*args, **kwargs)
            return async_wrapped

        @wraps(func)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            with timing_span(name):
                return func(*args, **kwargs)
        return wrapped
    return decorate


def trace_provider_operation(func: Callable) -> Callable:
    """Measure native SDK operations not going through the shared chat model."""
    @wraps(func)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        with timing_span("provider." + func.__name__, kind="model",
                         provider=self.provider_name):
            return func(self, *args, **kwargs)
    return wrapped


def trace_turn(channel: str) -> Callable:
    """Collect an entire entry point including intercepts, failures and delivery."""
    @contextmanager
    def scope() -> Iterator[None]:
        if current_timing() is not None:
            yield
            return
        timing = TurnTiming(channel)
        token = _active.set(timing)
        error = None
        try:
            yield
        except BaseException as exc:
            error = exc
            raise
        finally:
            try:
                timing.finish(error)
            except Exception:
                # Telemetry failure must not replace a successful result or error.
                timing.emit("latency_persistence_failed")
            finally:
                timing.closed = True
                _active.reset(token)

    def decorate(func: Callable) -> Callable:
        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapped(*args: Any, **kwargs: Any) -> Any:
                with scope():
                    return await func(*args, **kwargs)
            return async_wrapped

        @wraps(func)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            with scope():
                return func(*args, **kwargs)
        return wrapped
    return decorate


class ModelTimingCallback(BaseCallbackHandler):
    """Record LangChain calls, including direct invokes and bound tool models.

    A model span includes SDK-internal retries. on_retry exposes only retries
    reported by LangChain; it does not claim visibility into SDK internals.
    """

    run_inline = True

    def __init__(self, provider: str, model: str) -> None:
        self.provider = provider
        self.model = model
        self._runs: dict[Any, tuple[TurnTiming, float, str]] = {}
        self._lock = threading.RLock()

    def on_chat_model_start(self, serialized: Any, messages: Any, *, run_id: Any,
                            **kwargs: Any) -> None:
        """Retain timing context only; deliberately ignore serialized prompts."""
        timing = current_timing()
        if timing is None:
            return
        with self._lock:
            if len(self._runs) >= 1024:
                self._runs = {key: value for key, value in self._runs.items() if not value[0].closed}
            if len(self._runs) >= 1024:
                return
            self._runs[run_id] = (timing, time.monotonic(), _stage.get())
        timing.emit("model_started", provider=self.provider, model=self.model,
                    stage=_stage.get(), call_id=str(run_id))

    def on_llm_start(self, serialized: Any, prompts: Any, *, run_id: Any, **kwargs: Any) -> None:
        """Support non-chat LangChain models through the same timing contract."""
        self.on_chat_model_start(serialized, None, run_id=run_id)

    def _end(self, run_id: Any, error: str | None = None) -> None:
        """Close one call even when the callback executes on another worker."""
        with self._lock:
            run = self._runs.pop(run_id, None)
        if run is not None:
            timing, started, stage = run
            timing.record("model_call", started, kind="model", error=error,
                          provider=self.provider, model=self.model, stage=stage, call_id=str(run_id))

    def on_llm_end(self, response: Any, *, run_id: Any, **kwargs: Any) -> None:
        """Close successful calls without retaining model output."""
        self._end(run_id)

    def on_llm_error(self, error: BaseException, *, run_id: Any, **kwargs: Any) -> None:
        """Retain only exception class, never provider error payloads."""
        self._end(run_id, type(error).__name__)

    def on_retry(self, retry_state: Any, *, run_id: Any, **kwargs: Any) -> None:
        """Expose a callback-reported retry without inferring hidden SDK attempts."""
        with self._lock:
            run = self._runs.get(run_id)
        if run is not None:
            run[0].record("langchain_retry", time.monotonic(), kind="retry",
                          attempt=int(retry_state.attempt_number))
