"""Additive dated routine ledger, explicitly initialized through memory APIs.

No production imports or migration occur on module import. The caller supplies
the canonical routine connection factory; tests supply temporary SQLite stores.
"""
from __future__ import annotations

import sqlite3
import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterator
from collections.abc import Mapping
from pathlib import Path

from services.routine_feedback import ATHENS, Feedback, FeedbackPressure, Occurrence, aware, evaluate_feedback
from memory.routine_pause import apply_indefinite_pause
from services.routine_completion_helper import RoutineFeedbackQuestion, RoutineFeedbackGroupQuestion


@dataclass(frozen=True)
class FeedbackCandidate:
    """Canonical identity evidence, dates and revision from one read snapshot."""

    routine_id: int
    name: str
    allowed_dates: frozenset[date]
    revision: str
    identity_evidence: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PendingDeliveryProof:
    """Immutable transport proof awaiting only canonical ledger recording."""

    routine_id: int
    occurrence_date: date
    delivered_at: datetime
    receipt_id: str
    channel: str
    question: str | None
    draft_event: str | None = None


@dataclass(frozen=True)
class PendingHistoryRepair:
    """Confirmed text and original transport identity, awaiting history only."""

    proof: PendingDeliveryProof
    content: str


class _BatchClaimRejected(Exception):
    """Rollback the entire group when one member cannot be reserved."""


class _BatchDeliveryRejected(Exception):
    """Rollback shared receipt staging when any reserved member conflicts."""


class RoutineFeedbackStore:
    """Serialize dated receipts/feedback across processes using SQLite writes."""

    def __init__(self, connection_factory: Callable[[], sqlite3.Connection]) -> None:
        """Retain the connection abstraction without touching storage."""
        self.connection_factory = connection_factory

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        """Rollback and release the connection on any failed mutation."""
        connection = self.connection_factory()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create only the approved occurrence table, without historical guesses."""
        with self._write() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS routine_occurrences (
                    routine_id INTEGER NOT NULL REFERENCES routines(id),
                    occurrence_date TEXT NOT NULL,
                    delivered_at TEXT,
                    receipt_id TEXT,
                    feedback TEXT CHECK(feedback IN
                        ('complete','acknowledge','skip_today','pause','defer')),
                    feedback_at TEXT,
                    baseline_at TEXT,
                    PRIMARY KEY (routine_id, occurrence_date),
                    CHECK ((delivered_at IS NULL) = (receipt_id IS NULL)),
                    CHECK ((feedback IS NULL) = (feedback_at IS NULL))
                )
            """)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(routine_occurrences)")}
            if "baseline_at" not in columns:
                connection.execute("ALTER TABLE routine_occurrences ADD COLUMN baseline_at TEXT")
            for column in ("question_text", "delivery_channel", "dispatch_started_at",
                           "staged_receipt_id", "staged_delivered_at", "staged_channel", "staged_question",
                           "pending_history_json", "staged_draft_event"):
                if column not in columns:
                    connection.execute(f"ALTER TABLE routine_occurrences ADD COLUMN {column} TEXT")

    def stage_delivery(self, proof: PendingDeliveryProof, *, history_content: str | None = None) -> bool:
        """Commit bounded confirmed proof separately before the ledger projection.

        Staging requires an existing dispatch reservation and never replaces
        another receipt. Failure still leaves the send held, not retryable.
        """
        return self.stage_deliveries((proof,), history_content=history_content)

    def stage_deliveries(self, proofs: tuple[PendingDeliveryProof, ...], *,
                         history_content: str | None = None) -> bool:
        """Durably stage one confirmed send for every reserved member atomically.

        A rollback retains reservations, never authorizes resend. Shared history
        work uses the same transport identity, so replay inserts one message.
        No schema initialization, delivery or question inference takes place.
        """
        proofs = tuple(proofs)
        if not proofs or any(not isinstance(proof, PendingDeliveryProof) for proof in proofs):
            raise ValueError("Confirmed delivery proofs are required")
        identities = {(proof.routine_id, proof.occurrence_date) for proof in proofs}
        shared = {(proof.receipt_id, aware(proof.delivered_at), proof.channel,
                   proof.occurrence_date) for proof in proofs}
        if len(identities) != len(proofs) or len(shared) != 1:
            raise ValueError("Group proofs must identify one shared delivery")
        if len(proofs) != 1 and any(proof.draft_event is not None for proof in proofs):
            raise ValueError("Draft offers require one routine")
        try:
            with self._write() as connection:
                for proof in proofs:
                    if not self._stage_delivery(connection, proof, history_content=history_content):
                        raise _BatchDeliveryRejected()
            return True
        except _BatchDeliveryRejected:
            return False

    def _stage_delivery(self, connection: sqlite3.Connection, proof: PendingDeliveryProof, *,
                        history_content: str | None = None) -> bool:
        """Validate and retain one immutable proof inside the caller's transaction."""
        self._identity(proof.routine_id, proof.occurrence_date, proof.delivered_at)
        if (proof.channel not in ("matrix", "telegram")
                or not isinstance(proof.receipt_id, str) or not proof.receipt_id.strip()
                or len(proof.receipt_id) > 512
                or (proof.question is not None and (not isinstance(proof.question, str)
                    or not proof.question.strip() or len(proof.question) > 2000))):
            raise ValueError("Invalid staged delivery proof")
        if proof.draft_event is not None and (proof.question is not None
                or not isinstance(proof.draft_event, str) or not proof.draft_event.strip()
                or len(proof.draft_event) > 2000):
            raise ValueError("A bounded draft event requires separate question scope")
        values = (proof.receipt_id, aware(proof.delivered_at).isoformat(), proof.channel,
                  proof.question, proof.draft_event)
        if history_content is not None and (not isinstance(history_content, str)
                or not history_content.strip() or len(history_content) > 20000):
            raise ValueError("A bounded history payload is required")
        row = connection.execute("""SELECT dispatch_started_at, receipt_id, delivered_at,
            staged_receipt_id, staged_delivered_at, staged_channel, staged_question, staged_draft_event
            FROM routine_occurrences WHERE routine_id=? AND occurrence_date=?""",
            (proof.routine_id, proof.occurrence_date.isoformat())).fetchone()
        if row is None or row[0] is None:
            return False
        if row[1] is not None:
            if row[1:3] != values[:2]:
                return False
        elif row[3] is not None:
            if row[3:] != values:
                return False
        else:
            connection.execute("""UPDATE routine_occurrences SET staged_receipt_id=?,
                staged_delivered_at=?, staged_channel=?, staged_question=?, staged_draft_event=?
                WHERE routine_id=? AND occurrence_date=?""",
                (*values, proof.routine_id, proof.occurrence_date.isoformat()))
        if history_content is not None:
            connection.execute("""UPDATE routine_occurrences SET pending_history_json=?
                WHERE routine_id=? AND occurrence_date=? AND pending_history_json IS NULL""",
                (self._history_payload(PendingHistoryRepair(proof, history_content)),
                 proof.routine_id, proof.occurrence_date.isoformat()))
        return True

    @staticmethod
    def _history_payload(item: PendingHistoryRepair) -> str:
        """Serialize immutable repair data for exact acknowledgement."""
        proof = item.proof
        payload = [proof.delivered_at.isoformat(), proof.receipt_id,
                   proof.channel, proof.question, item.content]
        if proof.draft_event is not None:
            payload.append(proof.draft_event)
        return json.dumps(payload, ensure_ascii=False)

    def pending_history_repairs(self) -> tuple[PendingHistoryRepair, ...]:
        """Read pending history even after canonical receipt recording succeeds."""
        connection = self.connection_factory()
        try:
            rows = connection.execute("""SELECT routine_id, occurrence_date, pending_history_json
                FROM routine_occurrences WHERE pending_history_json IS NOT NULL
                ORDER BY occurrence_date, routine_id""").fetchall()
            result = []
            for rid, day, payload in rows:
                values = json.loads(payload)
                at, receipt, channel, question, content = values[:5]
                draft_event = values[5] if len(values) == 6 else None
                proof = PendingDeliveryProof(rid, date.fromisoformat(day),
                    aware(datetime.fromisoformat(at)), receipt, channel, question, draft_event)
                if (channel not in ("matrix", "telegram") or not isinstance(receipt, str)
                        or not receipt.strip() or len(receipt) > 512
                        or not isinstance(content, str) or not content.strip() or len(content) > 20000):
                    raise ValueError("Invalid persisted history repair")
                result.append(PendingHistoryRepair(proof, content))
            return tuple(result)
        finally:
            connection.close()

    def acknowledge_history_repair(self, item: PendingHistoryRepair) -> bool:
        """Clear only the exact payload whose idempotent history write succeeded."""
        with self._write() as connection:
            return connection.execute("""UPDATE routine_occurrences SET pending_history_json=NULL
                WHERE routine_id=? AND occurrence_date=? AND pending_history_json=?""",
                (item.proof.routine_id, item.proof.occurrence_date.isoformat(),
                 self._history_payload(item))).rowcount == 1

    def pending_delivery_proofs(self) -> tuple[PendingDeliveryProof, ...]:
        """Read durable repair work without releasing claims or contacting transport."""
        connection = self.connection_factory()
        try:
            rows = connection.execute("""SELECT routine_id, occurrence_date,
                staged_delivered_at, staged_receipt_id, staged_channel, staged_question, staged_draft_event
                FROM routine_occurrences WHERE staged_receipt_id IS NOT NULL
                ORDER BY occurrence_date, routine_id""").fetchall()
            return tuple(PendingDeliveryProof(rid, date.fromisoformat(day),
                         aware(datetime.fromisoformat(at)), receipt, channel, question, draft_event)
                         for rid, day, at, receipt, channel, question, draft_event in rows)
        finally:
            connection.close()

    def claim_dispatch(self, routine_id: int, occurrence_date: date, *,
                       at: datetime, expected_revision: str,
                       is_eligible: Callable[[], bool]) -> bool:
        """Reserve today's send once, requiring the caller's canonical eligibility.

        A claim is not a receipt. It survives restart and holds uncertain sends
        without inventing unanswered pressure. No network operation runs under
        the transaction. Production eligibility/scheduler wiring remains opt-in.
        """
        at = self._identity(routine_id, occurrence_date, at)
        if occurrence_date != at.date():
            return False
        with self._write() as connection:
            return self._claim_dispatch(connection, routine_id, occurrence_date,
                at=at, expected_revision=expected_revision, is_eligible=is_eligible)

    def claim_batch_dispatch(self, revisions: Mapping[int, str], occurrence_date: date, *,
                             at: datetime, is_eligible: Callable[[], bool]) -> bool:
        """Reserve every member of one message atomically, or leave all unchanged.

        Uses the single-send policy under the same write transaction. The caller
        checks canonical eligibility for the whole group without sending; receipt
        staging and actual group transport are separate, still-inactive slices.
        """
        if not isinstance(revisions, Mapping) or not revisions:
            raise ValueError("A nonempty group of canonical revisions is required")
        revisions = dict(revisions)
        for routine_id, revision in revisions.items():
            at = self._identity(routine_id, occurrence_date, at)
            if not isinstance(revision, str) or not revision:
                raise ValueError("A canonical revision is required for every member")
        if occurrence_date != at.date():
            return False
        try:
            with self._write() as connection:
                if is_eligible() is not True:
                    raise _BatchClaimRejected()
                for routine_id, revision in revisions.items():
                    if not self._claim_dispatch(connection, routine_id, occurrence_date,
                                                at=at, expected_revision=revision):
                        raise _BatchClaimRejected()
            return True
        except _BatchClaimRejected:
            return False

    def _claim_dispatch(self, connection: sqlite3.Connection, routine_id: int,
                        occurrence_date: date, *, at: datetime, expected_revision: str,
                        is_eligible: Callable[[], bool] | None = None) -> bool:
        """Apply one canonical reservation within the caller's locked transaction."""
        if (self._revision(connection, routine_id) != expected_revision
                or (is_eligible is not None and is_eligible() is not True)):
            return False
        pressure = self._project(connection, routine_id, now=at)
        if pressure.cooldown_until and at < pressure.cooldown_until:
            return False
        self._ensure_row(connection, routine_id, occurrence_date)
        result = connection.execute("""UPDATE routine_occurrences
            SET dispatch_started_at=? WHERE routine_id=? AND occurrence_date=?
            AND dispatch_started_at IS NULL AND delivered_at IS NULL
            AND (feedback IS NULL OR feedback='acknowledge')""",
            (at.isoformat(), routine_id, occurrence_date.isoformat()))
        return result.rowcount == 1

    @staticmethod
    def _identity(routine_id: int, occurrence_date: date, at: datetime) -> datetime:
        """Validate structured identity and temporal bounds, not user wording."""
        if type(routine_id) is not int or routine_id <= 0 or type(occurrence_date) is not date:
            raise ValueError("Invalid routine occurrence identity")
        at = aware(at)
        if occurrence_date > at.date():
            raise ValueError("Cannot record evidence for a future occurrence")
        return at

    @staticmethod
    def _ensure_row(connection: sqlite3.Connection, routine_id: int, day: date) -> None:
        """Reject unknown routines even if the connection disables foreign keys."""
        if connection.execute("SELECT id FROM routines WHERE id=?", (routine_id,)).fetchone() is None:
            raise ValueError("Unknown routine")
        connection.execute("""INSERT OR IGNORE INTO routine_occurrences
            (routine_id, occurrence_date) VALUES (?, ?)""", (routine_id, day.isoformat()))

    def record_delivery(self, routine_id: int, occurrence_date: date, *,
                        at: datetime, receipt_id: str, question: str | None = None,
                        channel: str | None = None,
                        draft_event: str | None = None,
                        reconciled_at: datetime | None = None) -> bool:
        """Persist confirmed proof at its original instant, evaluating pressure now."""
        at = self._identity(routine_id, occurrence_date, at)
        reconciled_at = aware(reconciled_at) if reconciled_at is not None else at
        if at > reconciled_at:
            raise ValueError("Cannot reconcile a future delivery")
        if not isinstance(receipt_id, str) or not receipt_id.strip() or len(receipt_id) > 512:
            raise ValueError("A bounded confirmed transport receipt is required")
        if question is not None or channel is not None:
            if (channel not in ("web", "matrix", "telegram")
                    or not isinstance(question, str) or not question.strip() or len(question) > 2000):
                raise ValueError("A bounded actual question and delivery channel are required together")
        if draft_event is not None and (question is not None or channel is not None
                or not isinstance(draft_event, str) or not draft_event.strip() or len(draft_event) > 2000):
            raise ValueError("Draft offers cannot grant ordinary question scope")
        with self._write() as connection:
            self._ensure_row(connection, routine_id, occurrence_date)
            result = connection.execute("""UPDATE routine_occurrences
                SET delivered_at=?, receipt_id=?, question_text=?, delivery_channel=? WHERE routine_id=?
                AND occurrence_date=? AND delivered_at IS NULL""",
                (at.isoformat(), receipt_id, question, channel, routine_id, occurrence_date.isoformat()))
            if result.rowcount == 1:
                if draft_event is not None:
                    self._record_draft_window(connection, routine_id, draft_event, at, reconciled_at)
                self._project(connection, routine_id, now=reconciled_at)
            connection.execute("""UPDATE routine_occurrences SET staged_receipt_id=NULL,
                staged_delivered_at=NULL, staged_channel=NULL, staged_question=NULL, staged_draft_event=NULL
                WHERE routine_id=? AND occurrence_date=? AND receipt_id=staged_receipt_id
                AND delivered_at=staged_delivered_at""", (routine_id, occurrence_date.isoformat()))
            return result.rowcount == 1

    @staticmethod
    def _record_draft_window(connection: sqlite3.Connection, routine_id: int,
                             event: str, at: datetime, now: datetime) -> None:
        """Join a fresh offer to receipt recording, never resurrect consumed offers."""
        if at.date() != now.date() or now.astimezone(timezone.utc) - at.astimezone(timezone.utc) >= timedelta(minutes=30):
            return
        row = connection.execute("""SELECT r.state, r.event_name, o.feedback FROM routines r
            JOIN routine_occurrences o ON o.routine_id=r.id
            WHERE r.id=? AND o.occurrence_date=?""", (routine_id, at.date().isoformat())).fetchone()
        if row is None or row[0] not in ("active", "trigger_pending") or row[1] != event or row[2] is not None:
            return
        inserted = connection.execute("""INSERT OR IGNORE INTO pending_confirmations
            (routine_id, event_name, sent_at, draft_offer) VALUES (?, ?, ?, 1)""",
            (routine_id, event, at.isoformat()))
        if inserted.rowcount == 1:
            connection.execute("UPDATE routines SET state='trigger_pending', is_active=0 WHERE id=?", (routine_id,))

    def is_delivered_question_target(self, *, channel: str, event_id: str) -> bool:
        """Identify a recorded reminder, including resolved targets for replay routing.

        This grants no feedback or tool authorization. Pending outcome/window
        checks still belong to pending_question and the saved-turn handler.
        Keeping resolved identity prevents a duplicate inbound event from being
        reinterpreted as a tool approval after its first feedback commit.
        """
        if (channel not in {"web", "matrix", "telegram"}
                or not isinstance(event_id, str) or not event_id.strip() or len(event_id) > 512):
            return False
        connection = self.connection_factory()
        try:
            return connection.execute("""SELECT 1 FROM routine_occurrences
                WHERE delivery_channel=? AND receipt_id=? AND delivered_at IS NOT NULL
                AND question_text IS NOT NULL AND length(trim(question_text)) > 0
                LIMIT 1""", (channel, event_id)).fetchone() is not None
        finally:
            connection.close()

    def pending_question(self, *, now: datetime, reply_channel: str | None = None,
                         reply_event_id: str | None = None) -> RoutineFeedbackQuestion | RoutineFeedbackGroupQuestion | None:
        """Load exact delivered context; never guess between pending reminders.

        Reply identifiers must come from the authenticated transport, not model
        output or user-supplied text. Explicit replies may identify an older
        occurrence; implicit context is limited to today's 30-minute response
        window. Window expiry does not mutate feedback or count a failure.
        Delivery callers must omit question metadata for Messenger draft offers
        and critical tool approvals, which use separate authorization paths.
        """
        now = aware(now)
        explicit = reply_channel is not None or reply_event_id is not None
        if explicit and (reply_channel not in ("web", "matrix", "telegram")
                         or not isinstance(reply_event_id, str) or not reply_event_id.strip()
                         or len(reply_event_id) > 512):
            return None
        connection = self.connection_factory()
        try:
            rows = connection.execute("""SELECT routine_id, occurrence_date, delivered_at,
                receipt_id, question_text, delivery_channel FROM routine_occurrences
                WHERE delivered_at IS NOT NULL AND feedback IS NULL
                AND question_text IS NOT NULL AND delivery_channel IS NOT NULL""")
            matches: list[RoutineFeedbackQuestion] = []
            identities: set[tuple[object, ...]] = set()
            for rid, day_text, sent_text, receipt, question, channel in rows:
                day = date.fromisoformat(day_text)
                sent = aware(datetime.fromisoformat(sent_text))
                elapsed = now.astimezone(timezone.utc) - sent.astimezone(timezone.utc)
                if day > now.date() or elapsed < timedelta(0):
                    continue
                if (channel not in ("web", "matrix", "telegram") or not question.strip()
                        or len(question) > 2000 or not receipt.strip() or len(receipt) > 512):
                    continue
                if explicit:
                    if channel != reply_channel or receipt != reply_event_id:
                        continue
                elif day != now.date() or elapsed >= timedelta(minutes=30):
                    continue
                matches.append(RoutineFeedbackQuestion(rid, day, receipt, question))
                identities.add((channel, receipt, day, sent, question))
                if len(identities) > 1:
                    return None
            if len(matches) > 1:
                first = matches[0]
                return RoutineFeedbackGroupQuestion(tuple(sorted(item.routine_id for item in matches)),
                    first.occurrence_date, first.event_id, first.question)
            return matches[0] if matches else None
        finally:
            connection.close()

    def record_feedback(self, routine_id: int, occurrence_date: date,
                        feedback: Feedback, *, at: datetime,
                        expected_revision: str | None = None,
                        is_current: Callable[[], bool] | None = None) -> bool:
        """Apply trusted feedback once; stale updates cannot undo completion."""
        at = self._identity(routine_id, occurrence_date, at)
        if feedback not in ("complete", "acknowledge", "skip_today", "pause", "defer"):
            raise ValueError("Invalid feedback outcome")
        with self._write() as connection:
            if expected_revision is not None:
                if (self._revision(connection, routine_id) != expected_revision
                        or is_current is None or is_current() is not True):
                    return False
            return self._record_feedback(connection, routine_id, occurrence_date, feedback, at=at)

    def record_draft_acknowledgement(self, connection: sqlite3.Connection,
                                    routine_id: int, *, offered_at: datetime,
                                    at: datetime) -> bool:
        """Record engagement inside the canonical exact-offer consume transaction.

        The caller has matched the pending draft and created the local draft.
        Never open a second transaction, fabricate delivery, or record completion.
        This callback is not installed by importing or constructing the store.
        """
        # Canonical legacy offer timestamps and its local clock use Athens wall time.
        offered_at = aware(offered_at.replace(tzinfo=ATHENS) if offered_at.tzinfo is None else offered_at)
        at = aware(at.replace(tzinfo=ATHENS) if at.tzinfo is None else at)
        if (not connection.in_transaction or offered_at.date() != at.date()
                or not timedelta(0) <= at.astimezone(timezone.utc) - offered_at.astimezone(timezone.utc)
                < timedelta(minutes=30)):
            return False
        at = self._identity(routine_id, offered_at.date(), at)
        return self._record_feedback(connection, routine_id, offered_at.date(), "acknowledge", at=at)

    def close_response_window(self, routine_id: int, *, sent_at: datetime, now: datetime) -> bool:
        """Close the exact legacy conversation window without daily failure accounting.

        Used only by an explicitly installed dated-rollout callback. Receipt,
        feedback, confidence and backoff remain untouched, including old windows
        without sufficient evidence to invent a successful delivery.
        """
        sent_text = sent_at.isoformat()
        sent = aware(sent_at.replace(tzinfo=ATHENS) if sent_at.tzinfo is None else sent_at)
        now = aware(now.replace(tzinfo=ATHENS) if now.tzinfo is None else now)
        if type(routine_id) is not int or routine_id <= 0:
            return False
        if now.astimezone(timezone.utc) - sent.astimezone(timezone.utc) <= timedelta(minutes=30):
            return False
        with self._write() as connection:
            deleted = connection.execute("DELETE FROM pending_confirmations WHERE routine_id=? AND sent_at=?",
                                         (routine_id, sent_text))
            if deleted.rowcount != 1:
                return False
            connection.execute("""UPDATE routines SET state='active', is_active=1
                WHERE id=? AND state='trigger_pending'""", (routine_id,))
            return True

    def _record_feedback(self, connection: sqlite3.Connection, routine_id: int,
                         occurrence_date: date, feedback: Feedback, *, at: datetime) -> bool:
        """Apply one outcome on an already locked canonical transaction."""
        self._ensure_row(connection, routine_id, occurrence_date)
        row = connection.execute("""SELECT feedback, feedback_at
                FROM routine_occurrences WHERE routine_id=? AND occurrence_date=?""",
                (routine_id, occurrence_date.isoformat())).fetchone()
        if row[1] and aware(datetime.fromisoformat(row[1])).astimezone(timezone.utc) >= at.astimezone(timezone.utc):
            return False
        if row[0] == "complete" and feedback != "pause":
            return False
        if row[0] != "complete":
            connection.execute("""UPDATE routine_occurrences SET feedback=?, feedback_at=?
                    WHERE routine_id=? AND occurrence_date=?""",
                    (feedback, at.isoformat(), routine_id, occurrence_date.isoformat()))
        if feedback == "pause":
            apply_indefinite_pause(connection, routine_id)
        self._project(connection, routine_id, now=at)
        return True

    @staticmethod
    def _revision(connection: sqlite3.Connection, routine_id: int) -> str:
        """Fingerprint routine configuration and all dated evidence on one snapshot."""
        routine = connection.execute("SELECT * FROM routines WHERE id=?", (routine_id,)).fetchone()
        if routine is None:
            raise ValueError("Unknown routine")
        rows = connection.execute("""SELECT * FROM routine_occurrences WHERE routine_id=?
            ORDER BY occurrence_date""", (routine_id,)).fetchall()
        payload = json.dumps([tuple(routine), [tuple(row) for row in rows]],
                             ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def revision(self, routine_id: int) -> str:
        """Capture a consistent read token before inference, without acquiring a write lock."""
        if type(routine_id) is not int or routine_id <= 0:
            raise ValueError("Invalid routine ID")
        connection = self.connection_factory()
        try:
            connection.execute("BEGIN")
            return self._revision(connection, routine_id)
        finally:
            connection.close()

    def feedback_candidates(self, *, now: datetime) -> tuple[FeedbackCandidate, ...]:
        """Read existing routines and recorded past dates without inventing history.

        Today permits an unprompted report before delivery. Historical feedback
        is restricted to recorded occurrences; no arbitrary lookback is added.
        Paused routines remain identifiable for historical corrections, but
        feedback never reactivates them. Dispatch eligibility is separate.
        """
        today = aware(now).date()
        connection = self.connection_factory()
        try:
            connection.execute("BEGIN")
            cursor = connection.execute("SELECT * FROM routines ORDER BY id")
            columns = [item[0] for item in cursor.description]
            routines = [dict(zip(columns, row)) for row in cursor.fetchall()]
            candidates = []
            for routine in routines:
                rid, name = routine["id"], routine["event_name"]
                if not isinstance(name, str) or not name.strip():
                    continue
                dates = {today}
                for (day_text,) in connection.execute(
                    "SELECT occurrence_date FROM routine_occurrences WHERE routine_id=?", (rid,)
                ):
                    day = date.fromisoformat(day_text)
                    if day <= today:
                        dates.add(day)
                occurrence_cursor = connection.execute(
                    """SELECT occurrence_date, delivered_at, feedback, feedback_at,
                              question_text, delivery_channel FROM routine_occurrences
                       WHERE routine_id=? AND occurrence_date<=?
                       ORDER BY occurrence_date DESC LIMIT 8""", (rid, today.isoformat()))
                occurrence_columns = [item[0] for item in occurrence_cursor.description]
                occurrences = [dict(zip(occurrence_columns, row))
                               for row in occurrence_cursor.fetchall()]
                for occurrence in occurrences:
                    if occurrence["question_text"] is not None:
                        occurrence["question_text"] = occurrence["question_text"][:2000]
                metadata = {key: routine[key] for key in (
                    "day_of_week", "time_str", "event_type", "conditions_json",
                    "condition_type", "condition_payload", "condition_mode", "state",
                    "is_active", "paused_until", "paused_indefinitely") if key in routine}
                candidates.append(FeedbackCandidate(rid, name, frozenset(dates),
                    self._revision(connection, rid),
                    {"routine": metadata, "occurrences": occurrences}))
            return tuple(candidates)
        finally:
            connection.close()

    def feedback_candidate_revisions(self) -> dict[int, str]:
        """Read the complete named candidate set and revisions on one snapshot."""
        connection = self.connection_factory()
        try:
            connection.execute("BEGIN")
            return {rid: self._revision(connection, rid)
                    for rid, name in connection.execute("SELECT id, event_name FROM routines")
                    if isinstance(name, str) and name.strip()}
        finally:
            connection.close()

    def closed_occurrence_ids(self, occurrence_date: date) -> set[int]:
        """Read dated outcomes that cannot claim dispatch; unmigrated stores stay legacy."""
        if type(occurrence_date) is not date:
            raise ValueError("Invalid occurrence date")
        connection = self.connection_factory()
        try:
            if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='routine_occurrences'").fetchone() is None:
                return set()
            return {row[0] for row in connection.execute(
                """SELECT routine_id FROM routine_occurrences WHERE occurrence_date=?
                AND feedback IS NOT NULL AND feedback!='acknowledge'""",
                (occurrence_date.isoformat(),)).fetchall()}
        finally:
            connection.close()

    def debug_snapshot(self, routine_ids: list[int], *, now: datetime) -> dict[int, dict]:
        """Inspect recorded/derived state consistently without projection or migration.

        Presence of a ledger proves recorded evidence, not live adapter activation.
        Callers must label derived policy as staged until rollout is complete.
        """
        now = aware(now)
        if any(type(rid) is not int or rid <= 0 for rid in routine_ids):
            raise ValueError("Invalid routine IDs")
        connection = self.connection_factory()
        try:
            connection.execute("BEGIN")
            exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='routine_occurrences'").fetchone()
            if not exists:
                return {rid: {"status": "uninitialized"} for rid in routine_ids}
            result = {}
            for rid in routine_ids:
                rows = self._occurrences(connection, rid)
                baseline = self._baseline(connection, rid)
                pressure = evaluate_feedback(rows, now=now, baseline_at=baseline)

                def details(row: Occurrence) -> dict:
                    """Expose evidence facts, never raw receipts or conversation content."""
                    return {"date": row.occurrence_date.isoformat(),
                            "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
                            "feedback": row.feedback,
                            "feedback_at": row.feedback_at.isoformat() if row.feedback_at else None}

                today = next((row for row in rows if row.occurrence_date == now.date()), None)
                remaining = None
                if pressure.cooldown_until:
                    seconds = (pressure.cooldown_until.astimezone(timezone.utc)
                               - now.astimezone(timezone.utc)).total_seconds()
                    remaining = round(max(0, seconds / 3600), 1)
                result[rid] = {"status": "recorded", "today": details(today) if today else None,
                    "latest_occurrence": details(rows[-1]) if rows else None,
                    "derived_cooldown_hours": pressure.cooldown_hours,
                    "backoff_until": pressure.cooldown_until.isoformat() if pressure.cooldown_until else None,
                    "backoff_remaining_h": remaining,
                    "unanswered_streak": pressure.unanswered_streak,
                    "refusal_streak": pressure.refusal_streak,
                    "baseline_at": baseline.isoformat() if baseline else None}
            return result
        finally:
            connection.close()

    @staticmethod
    def _occurrences(connection: sqlite3.Connection, routine_id: int) -> list[Occurrence]:
        """Load evidence on the same connection as its pressure projection."""
        rows = connection.execute("""SELECT occurrence_date, delivered_at, feedback, feedback_at
            FROM routine_occurrences WHERE routine_id=? ORDER BY occurrence_date""",
            (routine_id,)).fetchall()
        return [Occurrence(date.fromisoformat(row[0]),
                           aware(datetime.fromisoformat(row[1])) if row[1] else None,
                           row[2], aware(datetime.fromisoformat(row[3])) if row[3] else None)
                for row in rows]

    def _project(self, connection: sqlite3.Connection, routine_id: int, *,
                 now: datetime) -> FeedbackPressure:
        """Derive pressure atomically, without modifying confidence or dispatch state."""
        pressure = evaluate_feedback(self._occurrences(connection, routine_id), now=now,
                                     baseline_at=self._baseline(connection, routine_id))
        result = connection.execute("""UPDATE routines SET notify_cooldown_hours=?,
            explicit_skip_streak=?, unanswered_reminder_streak=? WHERE id=?""",
            (pressure.cooldown_hours, pressure.refusal_streak, pressure.unanswered_streak,
             routine_id))
        if result.rowcount != 1:
            raise ValueError("Unknown routine")
        return pressure

    @staticmethod
    def _baseline(connection: sqlite3.Connection, routine_id: int) -> datetime | None:
        """Load the latest durable reset instant, comparing instants rather than text."""
        rows = connection.execute("""SELECT baseline_at FROM routine_occurrences
            WHERE routine_id=? AND baseline_at IS NOT NULL""", (routine_id,)).fetchall()
        stamps = [aware(datetime.fromisoformat(row[0])).astimezone(timezone.utc) for row in rows]
        return max(stamps) if stamps else None

    def record_baseline(self, routine_id: int, *, at: datetime) -> FeedbackPressure:
        """Start a pressure epoch without erasing receipts or changing confidence.

        The eventual owner-authorized reset must snapshot protected state first.
        This method does not itself perform the bulk confidence reset.
        """
        at = self._identity(routine_id, aware(at).date(), at)
        with self._write() as connection:
            previous = self._baseline(connection, routine_id)
            if previous and at.astimezone(timezone.utc) < previous:
                raise ValueError("Cannot move the feedback baseline backwards")
            self._ensure_row(connection, routine_id, at.date())
            connection.execute("""UPDATE routine_occurrences SET baseline_at=?
                WHERE routine_id=? AND occurrence_date=?""",
                (at.astimezone(timezone.utc).isoformat(), routine_id, at.date().isoformat()))
            return self._project(connection, routine_id, now=at)

    def tracked_routine_ids(self) -> tuple[int, ...]:
        """List existing routines with dated evidence without initializing storage."""
        connection = self.connection_factory()
        try:
            return tuple(row[0] for row in connection.execute("""SELECT DISTINCT o.routine_id
                FROM routine_occurrences o JOIN routines r ON r.id=o.routine_id
                ORDER BY o.routine_id"""))
        finally:
            connection.close()

    def reset_feedback_baseline(self, *, at: datetime, snapshot_path: Path) -> tuple[int, ...]:
        """Explicit owner-only reset with an exclusive, consistent SQLite backup.

        Acquire the canonical writer lock before taking a separate reader backup.
        No receipt, completion, pause, schedule or history is deleted. The backup
        is retained only after a successful transaction; rollback removes only
        the new artifact owned by this call. This method never initializes schema.
        """
        at = aware(at)
        snapshot_path = Path(snapshot_path)
        if not snapshot_path.is_absolute():
            raise ValueError("Reset snapshot requires an absolute path")
        snapshot_path = snapshot_path.resolve()
        created = False
        try:
            with self._write() as connection:
                routine_ids = tuple(row[0] for row in connection.execute("SELECT id FROM routines ORDER BY id"))
                for rid in routine_ids:
                    baseline = self._baseline(connection, rid)
                    if baseline and at.astimezone(timezone.utc) < baseline:
                        raise ValueError("Cannot reset before the previous baseline")
                with snapshot_path.open("xb"):
                    created = True
                source = self.connection_factory()
                target = sqlite3.connect(snapshot_path)
                try:
                    source.backup(target)
                    if target.execute("PRAGMA quick_check").fetchone() != ("ok",):
                        raise RuntimeError("Reset backup verification failed")
                finally:
                    target.close()
                    source.close()
                with snapshot_path.open("r+b") as saved:
                    os.fsync(saved.fileno())
                columns = {row[1] for row in connection.execute("PRAGMA table_info(routines)")}
                assignments = ["notify_cooldown_hours=0", "confidence=1.0",
                               "explicit_skip_streak=0", "unanswered_reminder_streak=0"]
                assignments.extend(f"{name}=0" for name in ("ignore_count", "decay_counter") if name in columns)
                for rid in routine_ids:
                    self._ensure_row(connection, rid, at.date())
                    connection.execute("""UPDATE routine_occurrences SET baseline_at=?
                        WHERE routine_id=? AND occurrence_date=?""",
                        (at.astimezone(timezone.utc).isoformat(), rid, at.date().isoformat()))
                connection.execute("UPDATE routines SET " + ", ".join(assignments))
                verified = tuple(row[0] for row in connection.execute("""SELECT id FROM routines
                    WHERE notify_cooldown_hours=0 AND confidence=1.0
                      AND explicit_skip_streak=0 AND unanswered_reminder_streak=0 ORDER BY id"""))
                if verified != routine_ids:
                    raise RuntimeError("Reset readback verification failed")
            return routine_ids
        except BaseException:
            if created:
                snapshot_path.unlink()
            raise

    def reconcile(self, routine_id: int, *, now: datetime) -> FeedbackPressure:
        """Recompute closed-day pressure once per transaction; replay is harmless."""
        self._identity(routine_id, aware(now).date(), now)
        with self._write() as connection:
            return self._project(connection, routine_id, now=now)

    def occurrences(self, routine_id: int) -> list[Occurrence]:
        """Read a consistent ordered snapshot without creating or mutating rows."""
        if type(routine_id) is not int or routine_id <= 0:
            raise ValueError("Invalid routine ID")
        connection = self.connection_factory()
        try:
            return self._occurrences(connection, routine_id)
        finally:
            connection.close()


def load_initialized_feedback_store(db_path: str | Path, *,
                                    connection_factory: Callable[[], sqlite3.Connection]) -> RoutineFeedbackStore | None:
    """Detect explicit migration read-only; startup never creates owner storage.

    A present but incomplete schema is an error, not permission to switch back
    to legacy accounting. The supplied writer must be the canonical routine API.
    """
    path = Path(db_path).resolve()
    if not path.is_file():
        return None
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        if connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='routine_occurrences'").fetchone() is None:
            return None
        connection.execute("""SELECT routine_id, occurrence_date, delivered_at,
            receipt_id, feedback, feedback_at, baseline_at, question_text,
            delivery_channel, dispatch_started_at, staged_receipt_id,
            staged_delivered_at, staged_channel, staged_question,
            pending_history_json, staged_draft_event FROM routine_occurrences LIMIT 0""")
    finally:
        connection.close()
    return RoutineFeedbackStore(connection_factory)


def read_feedback_debug_snapshot(db_path: str, routine_ids: list[int], *, now: datetime) -> dict[int, dict]:
    """Open an existing database read-only; missing files are errors, not new stores."""
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    store = RoutineFeedbackStore(lambda: sqlite3.connect(uri, uri=True, timeout=2))
    return store.debug_snapshot(routine_ids, now=now)
