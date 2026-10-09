"""Shared dated routine-feedback orchestration behind authenticated channel adapters."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Literal, TYPE_CHECKING
from collections.abc import Mapping
from copy import deepcopy
from datetime import timedelta
from functools import partial
from inspect import signature

from services.routine_completion_helper import (
    DatedRoutineSelection, RoutineFeedbackQuestion, RoutineFeedbackGroupQuestion, validate_dated_selection,
)
from services.routine_feedback import aware

if TYPE_CHECKING:
    from langchain_core.messages import SystemMessage
    from memory.routine_feedback import RoutineFeedbackStore
    from services.matrix_routine_completion import MatrixRoutineDraftOffer
    from services.routine_completion_helper import RoutineSelection
    from memory.routine_context_clarification import ClarificationStore


def _context_question_store() -> ClarificationStore:
    """Open the canonical question abstraction without changing its lifecycle."""
    from pathlib import Path
    from config import BASE_DIR
    from memory.routine_context_clarification import ClarificationStore
    return ClarificationStore(Path(BASE_DIR) / "astakos_routine_context_questions.json")


def _feedback_conversation_reference(*, now: datetime, rowid: int, db_path: str) -> list[dict]:
    """Keep expired questions as meaning references, never active permissions."""
    from memory.conversation_history import load_recent_state_messages
    rows = load_recent_state_messages(now=now, through_rowid=rowid, db_path=db_path)
    requests = None
    references = []
    for row in rows:
        item = {key: row.get(key) for key in ("timestamp", "channel", "role")}
        item["content"] = str(row.get("content") or "")[:500]
        if row["role"] == "assistant":
            if requests is None:
                requests = {q["id"]: q for q in _context_question_store().snapshot()["requests"]}
            meta = row.get("metadata") or {}
            question = requests.get(meta.get("routine_context_question_id"))
            if (not question or question.get("external_id") != meta.get("external_message_id")
                    or not question.get("sent_at") or question["question"] != row["content"]
                    or question["channel"] != row["channel"]):
                continue
            item.update(routine_ids=question["routine_ids"], status=question["status"],
                        external_id=question["external_id"],
                        slot_at=question["slot_at"], kind="context_question_reference")
        references.append(item)
    return references


@dataclass(frozen=True)
class FeedbackTurnResult:
    """Separate persisted feedback from clarification or channel-level actions."""

    status: Literal["applied", "stale", "clarify", "none", "error"]
    selection: DatedRoutineSelection = DatedRoutineSelection("none")
    routine_name: str | None = None


class PersistedRoutineFeedbackHandler:
    """Injectable channel bridge from a saved owner turn to trusted graph context.

    Construct only behind the channel's authenticated-owner boundary. This
    class does not authenticate transport senders, initialize storage, consume
    draft offers or activate a live handler. Select it instead of the legacy
    mutation callback, never as a fall-through before that callback.
    """

    def __init__(
        self, *, store: RoutineFeedbackStore,
        selector: Callable[..., DatedRoutineSelection], clock: Callable[[], datetime],
        channel: str, conversation_db_path: str, trusted_owner: bool,
        draft_loader: Callable[[], Mapping[int, object]] | None = None,
        draft_selector: Callable[..., RoutineSelection] | None = None,
    ) -> None:
        if channel not in {"web", "telegram", "matrix"}:
            raise ValueError("Unsupported routine feedback channel")
        self._store = store
        self._selector = selector
        self._clock = clock
        self._channel = channel
        self._conversation_db_path = conversation_db_path
        self._trusted_owner = trusted_owner is True
        if (draft_loader is None) != (draft_selector is None):
            raise ValueError("Draft loader and semantic selector must be supplied together")
        self._draft_loader = draft_loader
        self._draft_selector = draft_selector

    def owns_reply_target(self, event_id: str) -> bool:
        """Route recorded receipt identity without granting any action permission.

        Wire alongside this handler during activation, never as a standalone
        live lookup. Storage failures propagate so transport fails closed.
        """
        return self._trusted_owner and self._store.is_delivered_question_target(
            channel=self._channel, event_id=event_id)

    def __call__(self, user_text: str, saved_user: Mapping[str, object], *,
                 reply_event_id: str | None = None) -> SystemMessage | MatrixRoutineDraftOffer | None:
        """Use the saved identity and caller-authenticated exact reply correlation."""
        from core.untrusted_content import external_content_source_names
        from services.routine_completion_context import build_dated_routine_feedback_context

        if not self._trusted_owner or not isinstance(saved_user, Mapping):
            return None
        rowid = saved_user.get("rowid")
        metadata = saved_user.get("metadata")
        if (type(rowid) is not int or rowid <= 0
                or saved_user.get("role") != "user"
                or saved_user.get("channel") != self._channel
                or saved_user.get("content") != user_text
                or (metadata is not None and not isinstance(metadata, Mapping))
                or external_content_source_names(metadata)):
            return None
        try:
            now = aware(self._clock())
            if reply_event_id is None and self._draft_loader is not None:
                draft = self._resolve_draft(user_text, rowid=rowid, now=now)
                if draft is not None:
                    return draft
            reference = _feedback_conversation_reference(now=now, rowid=rowid,
                db_path=self._conversation_db_path)
            selector = partial(self._selector, conversation_context=reference) if reference else self._selector
            expired_reply = reply_event_id is not None and any(
                item.get("kind") == "context_question_reference"
                and item.get("status") == "expired"
                and item.get("channel") == self._channel
                and item.get("external_id") == reply_event_id for item in reference)
            if expired_reply:
                original_selector = selector
                def select_execution(*args, **kwargs) -> DatedRoutineSelection:
                    """An expired state question permits only explicit execution feedback."""
                    selection = original_selector(*args, **kwargs)
                    return (selection if isinstance(selection, DatedRoutineSelection)
                            and selection.action in {"complete", "none", "clarify"}
                            else DatedRoutineSelection("none"))
                selector = select_execution
            result = process_catalog_feedback_turn(user_text, store=self._store,
                selector=selector, now=now, clock=self._clock,
                trusted=True, user_rowid=rowid, conversation_db_path=self._conversation_db_path,
                reply_channel=self._channel if reply_event_id is not None and not expired_reply else None,
                reply_event_id=None if expired_reply else reply_event_id)
        except Exception:
            result = FeedbackTurnResult("error")
        return build_dated_routine_feedback_context(result)

    def _resolve_draft(self, user_text: str, *, rowid: int, now: datetime) -> MatrixRoutineDraftOffer | SystemMessage | None:
        """Resolve only fresh structured local-draft offers, without consuming them.

        The canonical draft resolver is checked before and after inference.
        The graph's existing successful-draft receipt consumes the offer;
        this classification never records completion or sends a message.
        A changed offer or history ends this turn's routine arbitration; it
        must not be reclassified against a different pending question.
        """
        from services.routine_completion_context import get_pending_messenger_draft_offer
        from services.routine_completion_helper import decide_completion
        from services.matrix_routine_completion import MatrixRoutineDraftOffer
        from services.routine_feedback import ATHENS
        from core.messenger_draft import has_active_draft
        from services.routine_completion_context import build_dated_routine_feedback_context

        if has_active_draft():
            return None
        pending = deepcopy(dict(self._draft_loader()))
        offers = {}
        for rid, item in pending.items():
            if type(rid) is not int or not isinstance(item, Mapping):
                continue
            offered = item.get("sent_at")
            if not isinstance(offered, datetime) or get_pending_messenger_draft_offer(pending, rid) is None:
                continue
            offered = offered.replace(tzinfo=ATHENS) if offered.tzinfo is None else aware(offered)
            if offered.date() == now.date() and timedelta(0) <= now - offered < timedelta(minutes=30):
                offers[rid] = item
        if not offers:
            return None
        fresh = make_feedback_freshness(user_rowid=rowid, db_path=self._conversation_db_path,
            now=now, clock=self._clock,
            correlation_is_current=lambda: not has_active_draft()
                and dict(self._draft_loader()) == pending)
        if not fresh():
            return build_dated_routine_feedback_context(FeedbackTurnResult("stale"))
        decision = decide_completion(user_text=user_text,
            candidates={rid: str(item["event"]) + "\n[MESSENGER_DRAFT_OFFER]" for rid, item in offers.items()},
            pool="pending", semantic_selector=self._draft_selector,
            draft_offer_ids=frozenset(offers))
        if not fresh():
            return build_dated_routine_feedback_context(FeedbackTurnResult("stale"))
        if decision.action != "draft":
            return None
        item = offers[decision.routine_id]
        current = aware(self._clock())
        offered = item["sent_at"]
        offered = offered.replace(tzinfo=ATHENS) if offered.tzinfo is None else aware(offered)
        if current.date() != offered.date() or not timedelta(0) <= current - offered < timedelta(minutes=30):
            return build_dated_routine_feedback_context(FeedbackTurnResult("stale"))
        accepted = get_pending_messenger_draft_offer(offers, decision.routine_id)
        return MatrixRoutineDraftOffer(decision.routine_id, item["sent_at"], item["event"], accepted.context)


def make_feedback_freshness(
    *, user_rowid: int, db_path: str, now: datetime,
    clock: Callable[[], datetime], correlation_is_current: Callable[[], bool],
) -> Callable[[], bool]:
    """Reload shared history, Athens day and authenticated question correlation.

    Adapters must persist the authenticated inbound owner message first and
    pass its actual rowid, not the maximum rowid sampled later. The supplied
    correlation callback must reload the pending-question identity (or verify
    absence for unprompted feedback). This guard does not serialize separate
    databases: adapter turn arbitration still governs arrivals after the final
    check. The routine ledger independently checks its revision under its lock.
    """
    def fresh() -> bool:
        """Fail closed when identity, day, storage or question has changed."""
        if type(user_rowid) is not int or user_rowid <= 0:
            return False
        try:
            from memory.conversation_history import get_latest_trusted_user_rowid
            return (
                aware(clock()).date() == aware(now).date()
                and correlation_is_current() is True
                and get_latest_trusted_user_rowid(db_path=db_path) == user_rowid
            )
        except Exception:
            return False
    return fresh


def process_stored_feedback_turn(
    user_text: str, candidates: dict[int, str], allowed_dates: dict[int, frozenset[date]],
    *, store: RoutineFeedbackStore, selector: Callable[..., DatedRoutineSelection],
    now: datetime, clock: Callable[[], datetime], trusted: bool,
    user_rowid: int, conversation_db_path: str,
    reply_channel: str | None = None, reply_event_id: str | None = None,
    expected_revisions: dict[int, str] | None = None,
    catalog_is_current: Callable[[], bool] | None = None,
) -> FeedbackTurnResult:
    """Prepare persisted correlation/freshness for the shared inactive service.

    Channel adapters must authenticate the owner, persist their inbound message
    and validate reply metadata before calling. No inferred or fabricated IDs
    may replace transport receipts. Unknown explicit replies remain for their
    own handler, never fall back to a different routine's implicit question.
    """
    if trusted is not True:
        return FeedbackTurnResult("none")
    try:
        pending = store.pending_question(now=now, reply_channel=reply_channel,
                                         reply_event_id=reply_event_id)
        if (reply_channel is not None or reply_event_id is not None) and pending is None:
            return FeedbackTurnResult("none")
        if reply_event_id is not None:
            member_ids = (pending.routine_ids if isinstance(pending, RoutineFeedbackGroupQuestion)
                          else (pending.routine_id,))
            if any(rid not in candidates for rid in member_ids):
                return FeedbackTurnResult("none")
            candidates = {rid: candidates[rid] for rid in member_ids}
            allowed_dates = {rid: allowed_dates.get(rid, frozenset()) for rid in member_ids}

        def correlation_is_current() -> bool:
            """Reload the same delivery/outcome, including response-window expiry."""
            if catalog_is_current is not None and not catalog_is_current():
                return False
            return store.pending_question(now=clock(), reply_channel=reply_channel,
                                          reply_event_id=reply_event_id) == pending

        fresh = make_feedback_freshness(user_rowid=user_rowid,
            db_path=conversation_db_path, now=now, clock=clock,
            correlation_is_current=correlation_is_current)
        return process_feedback_turn(user_text, candidates, allowed_dates,
            store=store, selector=selector, now=now, trusted=True,
            is_current=fresh, pending_question=pending,
            expected_revisions=expected_revisions)
    except Exception:
        return FeedbackTurnResult("error")


def process_catalog_feedback_turn(
    user_text: str, *, store: RoutineFeedbackStore,
    selector: Callable[..., DatedRoutineSelection], now: datetime,
    clock: Callable[[], datetime], trusted: bool, user_rowid: int,
    conversation_db_path: str, reply_channel: str | None = None,
    reply_event_id: str | None = None,
) -> FeedbackTurnResult:
    """Compose canonical candidates and persisted-turn guards for every channel.

    This injectable entry point does not initialize storage or activate live
    adapters. Draft offers and tool approvals retain their separate handlers.
    """
    if trusted is not True:
        return FeedbackTurnResult("none")
    try:
        snapshot = store.feedback_candidates(now=now)

        def catalog_is_current() -> bool:
            """Reject identity decisions when any compared candidate has changed."""
            return store.feedback_candidate_revisions() == {
                item.routine_id: item.revision for item in snapshot}

        evidence = {item.routine_id: item.identity_evidence for item in snapshot}
        try:
            signature(selector).bind_partial(candidate_evidence=evidence)
        except (TypeError, ValueError):
            # Preserve fixed-signature injected consumers without retrying errors
            # raised inside a selector after inference has already started.
            pass
        else:
            selector = partial(selector, candidate_evidence=evidence)
        return process_stored_feedback_turn(user_text,
            {item.routine_id: item.name for item in snapshot},
            {item.routine_id: item.allowed_dates for item in snapshot},
            store=store, selector=selector, now=now, clock=clock, trusted=True,
            user_rowid=user_rowid, conversation_db_path=conversation_db_path,
            reply_channel=reply_channel, reply_event_id=reply_event_id,
            catalog_is_current=catalog_is_current,
            expected_revisions={item.routine_id: item.revision for item in snapshot})
    except Exception:
        return FeedbackTurnResult("error")


def process_feedback_turn(
    user_text: str, candidates: dict[int, str], allowed_dates: dict[int, frozenset[date]],
    *, store: RoutineFeedbackStore, selector: Callable[..., DatedRoutineSelection],
    now: datetime, trusted: bool, is_current: Callable[[], bool],
    pending_question: RoutineFeedbackQuestion | RoutineFeedbackGroupQuestion | None = None,
    expected_revisions: dict[int, str] | None = None,
) -> FeedbackTurnResult:
    """Classify then conditionally persist, rechecking freshness under the write lock.

    is_current must reload shared-history and pending-correlation versions; RF3
    adapters must supply it, not a cached boolean. No lock spans model inference.
    Pause commits canonical pause metadata and feedback in the same transaction.
    Deferral records engagement but returns clarification, never a new schedule.
    """
    if trusted is not True or not candidates:
        return FeedbackTurnResult("none")
    try:
        now = aware(now)
        candidates = dict(candidates)
        dates = {rid: frozenset(allowed_dates.get(rid, ())) for rid in candidates}
        if is_current() is not True:
            return FeedbackTurnResult("stale")
        revisions = {rid: store.revision(rid) for rid in candidates}
        if expected_revisions is not None:
            if any(expected_revisions.get(rid) != revisions[rid] for rid in candidates):
                return FeedbackTurnResult("stale")
            revisions = {rid: expected_revisions[rid] for rid in candidates}
        selection = selector(user_text, candidates, dates, now=now, trusted=True,
                             pending_question=pending_question)
        if not isinstance(selection, DatedRoutineSelection):
            return FeedbackTurnResult("none")
        selection = validate_dated_selection({"action": selection.action,
            "routine_id": selection.routine_id,
            "occurrence_date": selection.occurrence_date.isoformat() if selection.occurrence_date else None},
            dates, today=now.date())
        if is_current() is not True:
            return FeedbackTurnResult("stale")
        if selection.action == "none":
            return FeedbackTurnResult("none")
        if selection.action == "clarify":
            return FeedbackTurnResult("clarify", selection,
                                      routine_name=candidates.get(selection.routine_id))
        if selection.action == "complete" and any(
            row.occurrence_date == selection.occurrence_date and row.feedback == "complete"
            for row in store.occurrences(selection.routine_id)
        ):
            if is_current() is not True or store.revision(selection.routine_id) != revisions[selection.routine_id]:
                return FeedbackTurnResult("stale")
            return FeedbackTurnResult("applied", selection,
                                      routine_name=candidates.get(selection.routine_id))
        applied = store.record_feedback(selection.routine_id, selection.occurrence_date,
            selection.action, at=now, expected_revision=revisions[selection.routine_id],
            is_current=is_current)
        if not applied:
            return FeedbackTurnResult("stale", selection)
        return FeedbackTurnResult("clarify" if selection.action == "defer" else "applied",
                                  selection, routine_name=candidates.get(selection.routine_id))
    except Exception:
        return FeedbackTurnResult("error")
