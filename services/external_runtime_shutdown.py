"""Channel-neutral shutdown for the shared external background runtime."""

from __future__ import annotations

import threading
import time


def drain_and_archive_external_runtime(
    runtime: object,
    *,
    channel: str,
    drain_timeout: float = 30,
) -> bool:
    """Stop producers, finish queued work, then archive and close persistent memory."""
    runtime.shutdown_event.set()
    deadline = time.monotonic() + drain_timeout
    for producer_name in ("_external_scheduler_thread", "_external_missed_check_thread"):
        producer_thread = getattr(runtime, producer_name, None)
        if producer_thread is None:
            continue
        producer_thread.join(timeout=max(0, deadline - time.monotonic()))
        if producer_thread.is_alive():
            print(f"[{channel}]: Background producer {producer_name} did not stop.")
            return False

    drained = threading.Event()
    drain_errors: list[Exception] = []

    def drain_queues() -> None:
        """Wait for fast tasks and their downstream slow tasks to finish."""
        try:
            runtime.fast_queue.join()
            runtime.slow_queue.join()
        except Exception as exc:
            drain_errors.append(exc)
        finally:
            drained.set()

    threading.Thread(target=drain_queues, daemon=True).start()
    if not drained.wait(timeout=max(0, deadline - time.monotonic())) or drain_errors:
        print(f"[{channel}]: Background queues did not drain; archive skipped.")
        return False

    runtime._external_worker_stop_event.set()
    success = True
    try:
        from services.session_end import finalize_session

        finalize_session(channel=channel)
    except Exception as exc:
        success = False
        print(f"[{channel}]: Session-finalization warning: {exc}")

    try:
        from memory.vector_store import close_vector_store

        close_vector_store()
    except Exception as exc:
        success = False
        print(f"[{channel}]: Vector-store shutdown warning: {exc}")
    return success
