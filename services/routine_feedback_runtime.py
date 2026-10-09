"""Explicit paired routine composition; no migration, scheduler or reset on import."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from memory.routine_feedback import RoutineFeedbackStore
from services.routine_feedback_dispatch import DatedRoutineSender, maintain_dated_feedback
from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
from services.external_delivery import DeliveryReceipt


class RoutineFeedbackRuntime:
    """Prepare all dated dependencies before any worker uses them.

    Canonical routine setup must have provisioned storage. Installation is startup-only;
    this object never silently initializes a database or changes owner state.
    """

    def __init__(self, *, store: RoutineFeedbackStore, clock: Callable[[], datetime],
                 deliver: Callable[[str], DeliveryReceipt], record: Callable[..., object],
                 selector: Callable[..., Any], draft_loader: Callable[[], Any],
                 draft_selector: Callable[..., Any]) -> None:
        store.tracked_routine_ids()  # Read-only preflight; missing schema is fatal.
        self.store = store
        self.clock = clock
        self.record = record
        self.selector = selector
        self.draft_loader = draft_loader
        self.draft_selector = draft_selector
        self.sender = DatedRoutineSender(store, clock, deliver)

    def handler(self, *, channel: str, conversation_db_path: str) -> PersistedRoutineFeedbackHandler:
        """Create the common bridge behind the adapter's authenticated-owner gate."""
        return PersistedRoutineFeedbackHandler(store=self.store, clock=self.clock,
            selector=self.selector, channel=channel, trusted_owner=True,
            conversation_db_path=conversation_db_path, draft_loader=self.draft_loader,
            draft_selector=self.draft_selector)

    def tick(self, now: datetime) -> bool:
        """Reuse the existing tick for receipt repair and closed-day projection."""
        return maintain_dated_feedback(store=self.store, now=now, record=self.record)

    def install_scheduler(self, bot: Any, *, handler: PersistedRoutineFeedbackHandler,
                          routine_db: Any) -> None:
        """Install one complete dependency set before background workers start.

        Hot-swapping is intentionally rejected. The memory callback must use
        the same canonical database as this store; it joins the draft transaction.
        """
        if getattr(bot, "_external_background_runtime_channel", None) is not None:
            raise RuntimeError("Install dated feedback before starting the external worker")
        if handler._store is not self.store:
            raise ValueError("Scheduler and feedback handler must share the ledger")
        bot.__dict__.update(
            _persisted_routine_feedback_handler=handler,
            _dated_routine_feedback_tick=self.tick,
            _dated_single_routine_sender=self.sender,
            _dated_deferred_routine_sender=self.sender,
            _dated_batch_routine_sender=self.sender,
            _dated_pending_expiry_handler=self.store.close_response_window,
        )
        routine_db._dated_draft_feedback_recorder = self.store.record_draft_acknowledgement


def build_existing_routine_feedback_runtime() -> RoutineFeedbackRuntime | None:
    """Compose production dependencies after canonical routine setup's schema gate.

    No schema initialization, reset, model request or external send occurs here.
    Authentication remains enforced by the channel before invoking its handler.
    """
    from config import ROUTINES_DB
    from memory.routine_db import get_connection, load_pending_confirmations
    from memory.routine_feedback import load_initialized_feedback_store
    from memory.conversation_history import append_message
    from services.routine_completion_selector import select_dated_routine, select_routine
    from services.external_assistant_delivery import deliver_external_assistant_text
    from services.routine_feedback import ATHENS
    store = load_initialized_feedback_store(ROUTINES_DB, connection_factory=get_connection)
    if store is None:
        return None
    return RoutineFeedbackRuntime(store=store, clock=lambda: datetime.now(ATHENS),
        deliver=lambda text: deliver_external_assistant_text(text, agent="Routine_Agent"),
        record=append_message, selector=select_dated_routine,
        draft_loader=load_pending_confirmations, draft_selector=select_routine)
