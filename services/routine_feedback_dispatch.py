"""Inactive dated dispatch boundary; never registers a scheduler or opens storage."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import logging
from typing import Callable, Literal, Mapping

from memory.routine_feedback import PendingDeliveryProof, PendingHistoryRepair, RoutineFeedbackStore
from services.external_assistant_delivery import AssistantHistoryError, assistant_delivery_message_id
from services.external_delivery import DeliveryReceipt
from services.routine_feedback import aware


@dataclass(frozen=True)
class DatedDispatchResult:
    """Separate confirmed delivery, history repair and uncertain transport."""

    status: Literal["blocked", "sent", "uncertain", "recording_pending"]
    receipt: DeliveryReceipt | None = None
    history_repair: Callable[[], None] | None = None
    delivery_repair: Callable[[], bool] | None = None


@dataclass(frozen=True)
class DatedRoutineSender:
    """Explicit inactive scheduler dependency; never initializes live storage."""

    store: RoutineFeedbackStore
    now: Callable[[], datetime]
    deliver: Callable[[str], DeliveryReceipt]

    def revision(self, routine_id: int) -> str:
        """Capture canonical state before reminder generation."""
        return self.store.revision(routine_id)

    def send(self, *, routine_id: int, occurrence_date: date, text: str,
             expected_revision: str, eligible: Callable[[], bool],
             draft_event: str | None = None) -> DatedDispatchResult:
        """Use the reserved dated path, retaining only bounded actual prompt text."""
        return send_dated_reminder(store=self.store, routine_id=routine_id,
            occurrence_date=occurrence_date, text=text,
            question=text if draft_event is None and len(text) <= 2000 else None,
            draft_event=draft_event,
            now=self.now, expected_revision=expected_revision,
            eligible=eligible, deliver=self.deliver)

    def send_batch(self, *, occurrence_date: date, text: str,
                   expected_revisions: Mapping[int, str],
                   eligible: Callable[[], bool]) -> DatedDispatchResult:
        """Reserve all members and use one confirmed transport/history identity."""
        return send_dated_batch(store=self.store, occurrence_date=occurrence_date,
            text=text, question=text if len(text) <= 2000 else None,
            now=self.now, expected_revisions=expected_revisions,
            eligible=eligible, deliver=self.deliver)


def send_dated_reminder(*, store: RoutineFeedbackStore, routine_id: int,
                        occurrence_date: date, text: str, question: str | None,
                        now: Callable[[], datetime], expected_revision: str,
                        eligible: Callable[[], bool],
                        deliver: Callable[[str], DeliveryReceipt],
                        draft_event: str | None = None) -> DatedDispatchResult:
    """Use the same reservation/proof lifecycle as a one-member batch."""
    return send_dated_batch(store=store, occurrence_date=occurrence_date,
        text=text, question=question, now=now,
        expected_revisions={routine_id: expected_revision}, eligible=eligible, deliver=deliver,
        draft_event=draft_event)


def send_dated_batch(*, store: RoutineFeedbackStore, occurrence_date: date,
                     text: str, question: str | None, now: Callable[[], datetime],
                     expected_revisions: Mapping[int, str], eligible: Callable[[], bool],
                     deliver: Callable[[str], DeliveryReceipt],
                     draft_event: str | None = None) -> DatedDispatchResult:
    """Reserve all members, send once and stage shared proof atomically.

    The scheduler must supply its existing canonical eligibility and delivery
    functions. Draft offers/approvals must not supply question metadata. Unknown
    send outcomes stay reserved; recovering them is not permission to resend.
    """
    if not isinstance(text, str) or not text.strip() or len(text) > 20000:
        raise ValueError("A nonempty reminder is required")
    if question is not None and (not isinstance(question, str)
                                 or not question.strip() or len(question) > 2000):
        raise ValueError("A bounded actual question is required")
    at = aware(now())
    revisions = dict(expected_revisions)
    if draft_event is not None and (question is not None or len(revisions) != 1
            or not isinstance(draft_event, str) or not draft_event.strip() or len(draft_event) > 2000):
        raise ValueError("Draft offers require one bounded canonical event and separate scope")
    if not store.claim_batch_dispatch(revisions, occurrence_date, at=at,
                                     is_eligible=eligible):
        return DatedDispatchResult("blocked")
    repair = None
    try:
        receipt = deliver(text)
    except AssistantHistoryError as exc:
        receipt, repair = exc.receipt, exc.repair
    except Exception:
        return DatedDispatchResult("uncertain")
    if (not isinstance(receipt, DeliveryReceipt)
            or receipt.channel not in ("matrix", "telegram")
            or not isinstance(receipt.external_id, str)
            or not receipt.external_id.strip() or len(receipt.external_id) > 512):
        return DatedDispatchResult("uncertain")
    delivered_at = aware(now())
    proofs = tuple(PendingDeliveryProof(rid, occurrence_date, delivered_at,
                    receipt.external_id, receipt.channel, question, draft_event) for rid in revisions)

    def repair_delivery() -> bool:
        """Retry only the known receipt write, preserving its actual delivery time."""
        if not store.stage_deliveries(proofs, history_content=text if repair is not None else None):
            raise ValueError("Confirmed receipt conflicts with the reserved occurrence")
        for proof in proofs:
            store.record_delivery(proof.routine_id, occurrence_date, at=delivered_at,
                receipt_id=receipt.external_id, question=question,
                channel=receipt.channel if question is not None else None,
                draft_event=draft_event,
                reconciled_at=aware(now()))
        return True

    def repair_history() -> None:
        """Keep durable work until the original recorder acknowledges success."""
        if repair is not None:
            repair()
            for proof in proofs:
                store.acknowledge_history_repair(PendingHistoryRepair(proof, text))

    history_repair = repair_history if repair is not None else None
    # Neither a ledger failure nor history repair authorizes a second send.
    try:
        repair_delivery()
    except Exception:
        return DatedDispatchResult("recording_pending", receipt, history_repair, repair_delivery)
    return DatedDispatchResult("sent", receipt, history_repair)


def repair_pending_history(*, store: RoutineFeedbackStore, record: Callable[..., object]) -> int:
    """Replay confirmed history through an injected canonical recorder, never send.

    The recorder must honor stable message IDs. A lost commit acknowledgement
    therefore leaves retryable work without inserting a second conversation row.
    """
    repaired = 0
    for item in store.pending_history_repairs():
        proof = item.proof
        record(role="assistant", content=item.content, channel=proof.channel,
               agent="Routine_Agent", timestamp=proof.delivered_at,
               message_id=assistant_delivery_message_id(proof.channel, proof.receipt_id),
               metadata={"transport": proof.channel, "external_message_id": proof.receipt_id})
        repaired += int(store.acknowledge_history_repair(item))
    return repaired


def repair_staged_deliveries(*, store: RoutineFeedbackStore, now: datetime) -> int:
    """Recover committed transport proof after restart; never send or release claims."""
    now = aware(now)
    repaired = 0
    for proof in store.pending_delivery_proofs():
        if not store.stage_delivery(proof):
            continue
        repaired += int(store.record_delivery(proof.routine_id, proof.occurrence_date,
            at=proof.delivered_at, receipt_id=proof.receipt_id,
            question=proof.question, channel=proof.channel if proof.question is not None else None,
            draft_event=proof.draft_event,
            reconciled_at=now))
    return repaired


def maintain_dated_feedback(*, store: RoutineFeedbackStore, now: datetime,
                            record: Callable[..., object]) -> bool:
    """Recover confirmed writes and project closed days on an existing tick.

    Requires an explicitly initialized store and an idempotent canonical history
    recorder. No schema migration, scheduler registration or transport occurs.
    Receipt failures prevent pressure projection from incomplete evidence;
    independent history work can still progress. False means dispatch must stop.
    """
    now = aware(now)
    logger = logging.getLogger(__name__)
    receipts_ready = True
    healthy = True
    try:
        repair_staged_deliveries(store=store, now=now)
    except Exception as exc:
        logger.warning("Dated routine maintenance failed: receipts (%s)", type(exc).__name__)
        receipts_ready = healthy = False
    try:
        repair_pending_history(store=store, record=record)
    except Exception as exc:
        logger.warning("Dated routine maintenance failed: history (%s)", type(exc).__name__)
        healthy = False
    if receipts_ready:
        try:
            routine_ids = store.tracked_routine_ids()
        except Exception as exc:
            logger.warning("Dated routine maintenance failed: ledger scan (%s)", type(exc).__name__)
            return False
        for routine_id in routine_ids:
            try:
                store.reconcile(routine_id, now=now)
            except Exception as exc:
                logger.warning("Dated routine maintenance failed: projection #%s (%s)",
                               routine_id, type(exc).__name__)
                healthy = False
    return healthy
