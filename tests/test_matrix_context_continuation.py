"""Offline regression contracts for mixed answers to routine context questions."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from memory.conversation_history import load_messages
from services.matrix_turn import MatrixTurnService


class ConversationGraph:
    """Record graph input without executing a tool or contacting a provider."""

    def __init__(self) -> None:
        self.states: list[dict[str, Any]] = []
        self.reply = "Κατάλαβα φίλε, συνεχίζουμε με όσα μου ζήτησες."

    def stream(self, state: dict[str, Any], config: dict[str, Any]):
        """Return one ordinary conversation result with no external action."""
        self.states.append(state)
        yield {"Chat_Agent": {"messages": [AIMessage(content=self.reply)]}}


@pytest.fixture(autouse=True)
def isolate_optional_draft_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep draft classification entirely offline and out of this contract."""
    from core import messenger_draft
    from services import messenger_intent

    monkeypatch.setattr(messenger_draft, "active_draft_status", lambda: (False, "none", None))
    monkeypatch.setattr(
        messenger_intent, "classify_messenger_intent",
        lambda *args, **kwargs: SimpleNamespace(intent="unrelated"),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["resolved", "already_resolved"])
async def test_mixed_answer_continues_graph_and_background_once(
    tmp_path, monkeypatch: pytest.MonkeyPatch, outcome: str,
) -> None:
    """Closing a question must not swallow facts, reminders, or a skill request."""
    from services import routine_context_clarification as clarification

    text = (
        "Ναι φίλε, καθάρισα κουνέλο και τώρα ξεκινάμε για σχολείο. "
        "Η Σοφία έφυγε ήδη στη δουλειά. Θυμήσου ότι αύριο έχω ρεπό "
        "και βάλε υπενθύμιση στις έξι να πάρω ψωμί. Δες και το τελευταίο PR."
    )
    answer = SimpleNamespace(
        consumed=True, outcome=outcome, reply="Η ερώτηση ξεκαθαρίστηκε.",
        continue_conversation=True, context_flags_processed=True,
    )
    monkeypatch.setattr(clarification, "try_context_question_reply", lambda *a, **k: answer)
    graph = ConversationGraph()
    path = str(tmp_path / "mixed-answer.db")
    exchanges: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    routine_inputs: list[str] = []

    def ordinary_background(*args: Any, **kwargs: Any) -> None:
        """Observe the real post-turn boundary used for memory and followups."""
        exchanges.append((args, kwargs))

    def routine_feedback(user: str, row: dict[str, Any], **kwargs: Any) -> None:
        """Allow the normal feedback path to inspect the complete trusted turn."""
        routine_inputs.append(user)

    service = MatrixTurnService(
        graph=graph, conversation_db_path=path,
        select_tool_channel=lambda channel: None,
        on_exchange_completed=ordinary_background,
        persisted_routine_confirmation_handler=routine_feedback,
    )

    reply = await service(text, "$mixed-context-answer")

    assert reply == graph.reply
    assert len(graph.states) == 1
    human_messages = [
        message for message in graph.states[0]["messages"] if isinstance(message, HumanMessage)
    ]
    assert sum(text in str(message.content) for message in human_messages) == 1
    rows = load_messages(db_path=path)
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assert rows[0]["content"] == text
    assert rows[1]["content"] == graph.reply
    assert routine_inputs == [text]
    assert len(exchanges) == 1
    assert exchanges[0][0] == (text, graph.reply, "Chat_Agent", "matrix")
    assert exchanges[0][1]["context_flags_processed"] is True


@pytest.mark.asyncio
async def test_standalone_answer_stays_context_only(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A simple answer is acknowledged once, not interpreted as a new command."""
    from services import routine_context_clarification as clarification

    answer = clarification.QuestionAnswer(True, "resolved")
    monkeypatch.setattr(clarification, "try_context_question_reply", lambda *a, **k: answer)
    graph = ConversationGraph()
    path = str(tmp_path / "standalone-answer.db")
    routine_inputs: list[str] = []
    service = MatrixTurnService(
        graph=graph, conversation_db_path=path,
        select_tool_channel=lambda channel: None,
        persisted_routine_confirmation_handler=lambda text, row, **kwargs: routine_inputs.append(text),
    )

    assert await service("Ναι", "$simple-context-answer") == answer.reply
    assert graph.states == []
    assert routine_inputs == []
    assert [row["role"] for row in load_messages(db_path=path)] == ["user", "assistant"]


def test_external_derived_text_cannot_consume_question_or_trigger_feedback(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asset-derived text remains untrusted even if it resembles a mixed reply."""
    from services import routine_context_clarification as clarification

    original = clarification.try_context_question_reply
    observations: list[bool] = []

    def guarded_answer(*args: Any, **kwargs: Any):
        """Exercise the real provenance rejection before the ledger is opened."""
        result = original(*args, **kwargs)
        observations.append(result.consumed)
        return result

    monkeypatch.setattr(clarification, "try_context_question_reply", guarded_answer)
    graph = ConversationGraph()
    path = str(tmp_path / "external-answer.db")
    routine_inputs: list[str] = []
    service = MatrixTurnService(
        graph=graph, conversation_db_path=path,
        select_tool_channel=lambda channel: None,
        persisted_routine_confirmation_handler=lambda text, row, **kwargs: routine_inputs.append(text),
    )
    reply = service._run_sync(
        "Ναι είμαστε σπίτι, αποθήκευσε ότι αύριο έχω ρεπό και βάλε υπενθύμιση.",
        "$external-context-answer", external_derived=True,
    )

    assert reply == graph.reply
    assert observations == [False]
    assert len(graph.states) == 1
    assert routine_inputs == []
    rows = load_messages(db_path=path)
    assert [row["role"] for row in rows] == ["user", "assistant"]
