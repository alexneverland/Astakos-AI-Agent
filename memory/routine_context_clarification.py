"""Durable, bounded lifecycle for routine context clarification questions."""

from __future__ import annotations

import json
import os
import tempfile
from hashlib import sha256
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from filelock import FileLock


ATHENS = ZoneInfo("Europe/Athens")
MAX_DAILY_CONTEXT_QUESTIONS = 3
CONTEXT_REASK_INTERVAL = timedelta(minutes=30)
FINAL_STATES = frozenset({"resolved", "declined", "expired"})
VALID_STATES = FINAL_STATES | {"reserved", "sending", "sent"}


@dataclass(frozen=True)
class QuestionRequest:
    """A prepared question with stable identity and a bounded routine slot."""

    id: str
    topic: str
    routine_ids: tuple[str, ...]
    flags: tuple[str, ...]
    slot_at: datetime
    question: str
    channel: str
    correlation: str | None = None
    routine_slots: tuple[tuple[str, datetime], ...] = ()


def _aware(moment: datetime) -> datetime:
    """Require an explicit instant before comparing Athens day and slot."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("An aware timestamp is required")
    return moment.astimezone(ATHENS)


def _bounded_text(value: Any, limit: int = 500) -> bool:
    """Validate a persisted text field without interpreting its meaning."""
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def _stored_time(value: Any) -> datetime:
    """Parse an aware timestamp from the authoritative ledger."""
    if not isinstance(value, str):
        raise ValueError("Invalid clarification timestamp")
    return _aware(datetime.fromisoformat(value))


class ClarificationStore:
    """Serialize question reservations across the Web and external processes."""

    def __init__(self, path: str | Path) -> None:
        """Use an injected file path so tests never access the live ledger."""
        self.path = Path(path)

    def _lock(self) -> FileLock:
        """Hold a short cross-process lock for a single ledger transaction."""
        return FileLock(str(self.path) + ".lock", timeout=10)

    def _load(self) -> dict[str, Any]:
        """Read the ledger, treating absent and damaged files differently."""
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": 1, "requests": [], "evaluations": []}
        self._validate(state)
        return state

    @staticmethod
    def _validate(state: Any) -> None:
        """Reject malformed or unbounded state before any subsequent write."""
        if (not isinstance(state, dict) or set(state) != {"version", "requests", "evaluations"}
                or type(state["version"]) is not int or state["version"] != 1
                or not isinstance(state["requests"], list)
                or len(state["requests"]) > 64
                or not isinstance(state["evaluations"], list)
                or len(state["evaluations"]) > 128):
            raise ValueError("Invalid clarification ledger")
        for evaluation in state["evaluations"]:
            if (not isinstance(evaluation, dict) or not {"fingerprint", "day"} <= set(evaluation)
                    or set(evaluation) - {"fingerprint", "day", "flags"}
                    or not _bounded_text(evaluation["fingerprint"], 80)
                    or not isinstance(evaluation["day"], str)):
                raise ValueError("Invalid clarification evaluation")
            if "flags" in evaluation:
                from services.routine_context_evidence import VOLATILE_FLAGS
                flags = evaluation["flags"]
                if (not isinstance(flags, list) or len(flags) > 5
                        or any(flag not in VOLATILE_FLAGS for flag in flags)
                        or len(set(flags)) != len(flags)):
                    raise ValueError("Invalid semantic dependencies")
            try:
                from datetime import date
                if date.fromisoformat(evaluation["day"]).isoformat() != evaluation["day"]:
                    raise ValueError("Noncanonical evaluation day")
            except ValueError as exc:
                raise ValueError("Invalid clarification evaluation day") from exc
        seen: set[str] = set()
        for row in state["requests"]:
            required = {"id", "topic", "routine_ids", "flags", "slot_at", "question",
                        "channel", "created_at", "status", "external_id", "sent_at",
                        "closed_at", "history_recorded"}
            if (not isinstance(row, dict) or not required <= set(row)
                    or set(row) - required - {"correlation", "dispatch_pending", "routine_slots"}):
                raise ValueError("Invalid clarification request")
            if "dispatch_pending" in row and (
                    type(row["dispatch_pending"]) is not bool
                    or (row["dispatch_pending"] and row["status"] != "resolved")):
                raise ValueError("Invalid clarification dispatch request")
            if row.get("correlation") is not None and not _bounded_text(row["correlation"], 80):
                raise ValueError("Invalid clarification correlation")
            if (not _bounded_text(row["id"], 80) or row["id"] in seen
                    or not _bounded_text(row["topic"], 120)
                    or not _bounded_text(row["question"])):
                raise ValueError("Invalid clarification identity")
            seen.add(row["id"])
            for field in ("routine_ids", "flags"):
                values = row[field]
                if (not isinstance(values, list) or not 1 <= len(values) <= 5
                        or any(not _bounded_text(value, 100) for value in values)
                        or len(set(values)) != len(values)):
                    raise ValueError("Invalid clarification dependencies")
            if (not isinstance(row["channel"], str)
                    or row["channel"] not in ("matrix", "telegram")
                    or not isinstance(row["status"], str)
                    or row["status"] not in VALID_STATES):
                raise ValueError("Invalid clarification status")
            slot = _stored_time(row["slot_at"])
            created = _stored_time(row["created_at"])
            if slot <= created:
                raise ValueError("Invalid clarification deadline")
            if "routine_slots" in row:
                slots = row["routine_slots"]
                if (not isinstance(slots, dict) or set(slots) != set(row["routine_ids"])
                        or any(_stored_time(value) <= created for value in slots.values())
                        or min(_stored_time(value) for value in slots.values()) != slot):
                    raise ValueError("Invalid clarification routine slots")
            for field in ("sent_at", "closed_at"):
                if row[field] is not None:
                    _stored_time(row[field])
            if row["external_id"] is not None and not _bounded_text(row["external_id"], 200):
                raise ValueError("Invalid clarification receipt")
            if type(row["history_recorded"]) is not bool:
                raise ValueError("Invalid clarification history status")
            if row["history_recorded"] and row["external_id"] is None:
                raise ValueError("Missing recorded clarification receipt")
            if row["status"] in {"sent", "resolved", "declined"} and (
                    row["sent_at"] is None or row["external_id"] is None):
                raise ValueError("Missing clarification receipt")
            if (row["status"] in FINAL_STATES) != (row["closed_at"] is not None):
                raise ValueError("Invalid clarification closure")
        if sum(row["status"] not in FINAL_STATES for row in state["requests"]) > 1:
            raise ValueError("Multiple pending clarification questions")

    def _save(self, state: dict[str, Any]) -> None:
        """Replace a fully synced file while holding the process lock."""
        self._validate(state)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".routine-clarification-", suffix=".tmp", dir=self.path.parent,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(state, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def snapshot(self) -> dict[str, Any]:
        """Return current state and the sole pending record, without changing it."""
        with self._lock():
            state = self._load()
        pending = next((row for row in state["requests"] if row["status"] not in FINAL_STATES), None)
        return {"requests": state["requests"], "pending": pending}

    def claim_evaluation(self, fingerprint: str, *, now: datetime) -> bool:
        """Claim an unchanged semantic snapshot once across workers and polls."""
        current = _aware(now)
        if not _bounded_text(fingerprint, 80):
            raise ValueError("Invalid clarification fingerprint")
        with self._lock():
            state = self._load()
            day = current.date().isoformat()
            if any(item["day"] == day and item["fingerprint"] == fingerprint
                   for item in state["evaluations"]):
                return False
            if not self._append_evaluation(state, {"fingerprint": fingerprint, "day": day}, current):
                return False
            self._save(state)
            return True

    @staticmethod
    def _append_evaluation(state: dict[str, Any], row: dict[str, str], current: datetime) -> bool:
        """Keep today's note reservations under bounded dependency-cache churn."""
        retained = [item for item in state["evaluations"]
                    if item["fingerprint"].startswith("note-")
                    and item["day"] >= current.date().isoformat()]
        if len(retained) >= 128:
            return False  # Never evict a held send to make room for another evaluation.
        ordinary = [item for item in state["evaluations"] if item not in retained]
        if row["fingerprint"].startswith("note-"):
            retained.append(row)
        else:
            ordinary.append(row)
        room = 128 - len(retained)
        state["evaluations"] = (ordinary[-room:] if room else []) + retained
        return True

    def claim_context_note(self, routine_id: str, slot_at: datetime, *, now: datetime) -> bool:
        """Reserve a note once per Athens occurrence, without reminder feedback.

        The unchanged evaluation record schema holds the reservation before chance,
        inference or transport. An interrupted/uncertain attempt is not resendable.
        """
        current, slot = _aware(now), _aware(slot_at)
        if not isinstance(routine_id, str) or not routine_id.isdecimal() or int(routine_id) <= 0:
            raise ValueError("A canonical routine identity is required")
        if not 0 <= (slot - current).total_seconds() <= 900:
            return False
        day = slot.date().isoformat()
        key = "note-" + sha256(f"{int(routine_id)}:{day}".encode()).hexdigest()
        with self._lock():
            state = self._load()
            if any(item["fingerprint"] == key for item in state["evaluations"]):
                return False
            if not self._append_evaluation(state, {"fingerprint": key, "day": day}, current):
                return False
            self._save(state)
            return True

    def evaluation_flags(self, fingerprint: str, *, now: datetime) -> tuple[str, ...] | None:
        """Read validated dependency output; an unfinished/failed claim is unknown."""
        with self._lock():
            state = self._load()
            row = next((item for item in state["evaluations"]
                        if item["fingerprint"] == fingerprint
                        and item["day"] == _aware(now).date().isoformat()), None)
        return tuple(row["flags"]) if row is not None and "flags" in row else None

    def record_evaluation_flags(self, fingerprint: str, flags: tuple[str, ...], *, now: datetime) -> None:
        """Finalize one previously claimed tool-free dependency decision."""
        with self._lock():
            state = self._load()
            row = next((item for item in state["evaluations"]
                        if item["fingerprint"] == fingerprint
                        and item["day"] == _aware(now).date().isoformat()), None)
            if row is None:
                raise ValueError("Missing dependency claim")
            row["flags"] = list(flags)
            self._save(state)

    @staticmethod
    def _expire_pending(state: dict[str, Any], now: datetime) -> bool:
        """Close a question at its scheduled routine time."""
        for row in state["requests"]:
            if row["status"] not in FINAL_STATES and now >= _stored_time(row["slot_at"]):
                row["status"] = "expired"
                row["closed_at"] = now.isoformat()
                return True
        return False

    def expire(self, *, now: datetime) -> bool:
        """Persist expiry without resetting today's topic or send budget."""
        current = _aware(now)
        with self._lock():
            state = self._load()
            changed = self._expire_pending(state, current)
            if changed:
                self._save(state)
        return changed

    @staticmethod
    def _ask_allowed(state: dict[str, Any], routine_ids: tuple[str, ...],
                     flags: tuple[str, ...], current: datetime) -> bool:
        """Bound repeat questions by shared facts, routine identity and local day."""
        todays = [row for row in state["requests"]
                  if _stored_time(row["created_at"]).date() == current.date()]
        if (len(todays) >= MAX_DAILY_CONTEXT_QUESTIONS
                or any(row["status"] not in FINAL_STATES
                       and current < _stored_time(row["slot_at"])
                       for row in state["requests"])):
            return False
        for row in todays:
            if set(routine_ids).intersection(row["routine_ids"]):
                return False
            if set(flags).intersection(row["flags"]):
                reference = _stored_time(row["sent_at"] or row["created_at"])
                if (row["status"] == "declined"
                        or current - reference < CONTEXT_REASK_INTERVAL):
                    return False
        return True

    def can_ask(self, routine_ids: tuple[str, ...], flags: tuple[str, ...],
                *, now: datetime) -> bool:
        """Read the reservation policy before spending a semantic model attempt."""
        current = _aware(now)
        with self._lock():
            return self._ask_allowed(self._load(), routine_ids, flags, current)

    def reserve(self, question: QuestionRequest, *, now: datetime) -> bool:
        """Claim one question if its slot, topic and daily budget allow it."""
        current = _aware(now)
        slot = _aware(question.slot_at)
        if slot <= current:
            return False
        with self._lock():
            state = self._load()
            if self._expire_pending(state, current):
                self._save(state)
            if (not self._ask_allowed(state, question.routine_ids, question.flags, current)
                    or any(row["id"] == question.id for row in state["requests"])):
                return False
            state["requests"] = state["requests"][-63:]
            state["requests"].append({
                "id": question.id, "topic": question.topic,
                "routine_ids": list(question.routine_ids), "flags": list(question.flags),
                "slot_at": slot.isoformat(), "question": question.question,
                "channel": question.channel, "created_at": current.isoformat(),
                "status": "reserved", "external_id": None, "sent_at": None,
                "closed_at": None, "history_recorded": False,
                "correlation": question.correlation,
            })
            if question.routine_slots:
                if len(dict(question.routine_slots)) != len(question.routine_slots):
                    raise ValueError("Duplicate clarification routine slots")
                state["requests"][-1]["routine_slots"] = {
                    rid: _aware(at).isoformat() for rid, at in question.routine_slots}
            self._save(state)
            return True

    def begin_send(
        self, identifier: str, *, now: datetime,
        budget: Callable[[], bool] | None = None,
        current_time: Callable[[], datetime] | None = None,
    ) -> bool:
        """Persist intent before outbound delivery; do not retry uncertainty."""
        current = _aware(now)
        with self._lock():
            state = self._load()
            row = next((item for item in state["requests"] if item["id"] == identifier), None)
            if row is None or row["status"] != "reserved" or current >= _stored_time(row["slot_at"]):
                return False
            # Only a fast local budget gate belongs here, never model/transport I/O.
            if budget is not None and not budget():
                return False
            if current_time is not None and _aware(current_time()) >= _stored_time(row["slot_at"]):
                return False
            row["status"] = "sending"
            self._save(state)
            return True

    def mark_sent(self, identifier: str, *, external_id: str, now: datetime) -> bool:
        """Store a transport receipt once for an attempted question."""
        current = _aware(now)
        with self._lock():
            state = self._load()
            row = next((item for item in state["requests"] if item["id"] == identifier), None)
            if row is None or row["status"] != "sending":
                return False
            row.update(status="sent", external_id=external_id, sent_at=current.isoformat())
            self._save(state)
            return True

    @staticmethod
    def _close_request(row: dict[str, Any], *, outcome: str, now: datetime) -> None:
        """Finalize a question and request normal dispatch only on resolution."""
        row.update(status=outcome, closed_at=now.isoformat())
        if outcome == "resolved":
            row["dispatch_pending"] = True

    def close(self, identifier: str, *, outcome: str, now: datetime) -> bool:
        """Resolve or decline only a confirmed delivered question."""
        if outcome not in {"resolved", "declined"}:
            raise ValueError("Invalid clarification outcome")
        current = _aware(now)
        with self._lock():
            state = self._load()
            row = next((item for item in state["requests"] if item["id"] == identifier), None)
            if (row is None or row["status"] != "sent"
                    or current >= _stored_time(row["slot_at"])):
                return False
            self._close_request(row, outcome=outcome, now=current)
            self._save(state)
            return True

    def mark_recorded(self, identifier: str) -> bool:
        """Mark a confirmed question as present in canonical history."""
        with self._lock():
            state = self._load()
            row = next((item for item in state["requests"] if item["id"] == identifier), None)
            if row is None or not row["external_id"]:
                return False
            if row["history_recorded"]:
                return True
            row["history_recorded"] = True
            self._save(state)
            return True

    def commit_answer(
        self, identifier: str, *, received_at: datetime,
        current_time: Callable[[], datetime], persist: Callable[[], frozenset[str] | None],
        still_authoritative: Callable[[], bool],
    ) -> frozenset[str] | None:
        """Revalidate and serialize only the short persistence stage, never an LLM call.

        Database and ledger files cannot form one transaction. A ledger save
        failure leaves the request pending, never falsely resolved; canonical
        context setters remain retryable upserts.
        """
        received = _aware(received_at)
        with self._lock():
            state = self._load()
            row = next((item for item in state["requests"] if item["id"] == identifier), None)
            current = _aware(current_time())
            if (row is None or row["status"] != "sent" or not row["history_recorded"]
                    or not (_stored_time(row["sent_at"]) <= received <= current
                            < _stored_time(row["slot_at"]))
                    or not still_authoritative()):
                return None
            applied = persist()
            if applied is None:
                return None
            if set(row["flags"]) <= applied:
                self._close_request(row, outcome="resolved", now=current)
                self._save(state)
            return applied

    def claim_dispatch(self, *, now: datetime) -> bool:
        """Claim one timely canonical recheck after a committed complete answer.

        Old ledgers have no request. Expired requests are consumed without late
        replay. This is a wakeup, not authority to send or complete any routine.
        """
        current = _aware(now)
        with self._lock():
            state = self._load()
            pending = [row for row in state["requests"] if row.get("dispatch_pending")]
            if not pending:
                return False
            timely = any(current < _stored_time(row["slot_at"]) for row in pending)
            for row in pending:
                row["dispatch_pending"] = False
            self._save(state)
            return timely
