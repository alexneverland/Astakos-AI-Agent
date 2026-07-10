# ================================================================
# Project: Astakos AI Agent 🦞
# core/event_bus.py — Formal Event Bus (pub/sub)
# ================================================================

from collections import defaultdict
import threading


class EventBus:
    """
    Central pub/sub system of Astakos.
    Decouples components — no direct dependencies.

    Usage:
        from core.event_bus import bus
        bus.emit("routine_confirmed", routine_id=5, channel="telegram")
        bus.subscribe("routine_confirmed", my_handler)
    """

    def __init__(self):
        self._handlers: dict = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, event: str, handler):
        """Register a handler for an event."""
        with self._lock:
            self._handlers[event].append(handler)

    def emit(self, event_name: str, **payload):
        """Broadcast event to all subscribers."""
        with self._lock:
            handlers = list(self._handlers.get(event_name, []))
        for fn in handlers:
            try:
                fn(**payload)
            except Exception as e:
                print(f"[EventBus]: ⚠️ handler error on '{event_name}': {e}")

    def registered_events(self) -> list:
        """Debug: which events have subscribers."""
        with self._lock:
            return list(self._handlers.keys())


# ── Singleton — import from everywhere ───────────────────────────of_thought
bus = EventBus()

# ── Event List (documentation) ───────────────────────────
# routine_triggered  (routine_id, event, confidence, batch, channel)
# routine_confirmed  (routine_id, event, channel)
# routine_dismissed  (routine_id, event, channel)
# routine_timeout    (routine_id, event, elapsed_s, channel)
# session_ended      (channel, mood, summary)
# proactive_sent     (source, channel)
# TODO(future): event throttling + max_depth guard
# Needed when Analytics Engine subscribers go live.
# Pattern: event_source_tracking + prevent_self_trigger