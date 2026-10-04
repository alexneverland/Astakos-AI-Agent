"""Offline regressions for courtesy pollution and dated cross-writer facts."""

import contextlib
import json
from types import SimpleNamespace

import pytest

from memory import session_memory as sm
from memory import vector_store as vs
from services import gemini


def test_confirmation_is_not_a_user_fact() -> None:
    """An assistant acknowledgement must never become a deterministic fact."""
    assert sm._extract_confirmed_memory_candidate(
        "Από την επόμενη εβδομάδα έχω απογευματινή βάρδια στη δουλειά",
        "Σημειώθηκε. Καλή δύναμη με τις απογευματινές βάρδιες από αύριο.",
    ) is None


@pytest.fixture
def isolated_store(monkeypatch, tmp_path):
    """Exercise the actual manager write path with synthetic storage boundaries."""
    records = []
    manager = vs.AstakosMemoryManager()
    monkeypatch.setattr(sm, "STATE_DB", str(tmp_path / "sifter_state.db"))
    monkeypatch.setattr(vs, "_cross_process_lock", contextlib.nullcontext)
    monkeypatch.setattr(vs.embeddings, "embed_query", lambda text: [0.1])
    monkeypatch.setattr(vs.embeddings, "embed_documents", lambda texts: [[0.1]])
    monkeypatch.setattr(vs, "_fact_duplicate_model_response",
                        lambda prompt: gemini.safe_gemini_call(prompt, retries=1).text)
    monkeypatch.setattr(manager, "_trigger_routine_reconciler", lambda *a, **k: None)
    monkeypatch.setattr(vs, "_safe_chroma_delete", lambda *a: pytest.fail("No deletion allowed"))

    def query(**kwargs):
        selected = [r for r in records if not kwargs.get("where") or
                    r["meta"]["category"] == kwargs["where"].get("category")]
        selected = selected[:kwargs["n_results"]]
        return {"ids": [[r["id"] for r in selected]],
                "documents": [[r["text"] for r in selected]],
                "metadatas": [[r["meta"] for r in selected]],
                "distances": [[0.126 for r in selected]]}

    def get(**kwargs):
        selected = [r for r in records if r["id"] in kwargs["ids"]]
        return {"ids": [r["id"] for r in selected],
                "documents": [r["text"] for r in selected],
                "metadatas": [r["meta"] for r in selected]}

    def add(texts, *, metadatas, **kwargs):
        records.append({"id": str(len(records)), "text": texts[0], "meta": metadatas[0]})

    monkeypatch.setattr(vs, "_safe_chroma_query", query)
    monkeypatch.setattr(vs, "_safe_chroma_get", get)
    monkeypatch.setattr(vs, "_safe_chroma_add_texts", add)
    return manager, records


@pytest.mark.parametrize("second_category", ["work", "lazaros"])
def test_same_week_cross_category_translation_saved_once(isolated_store, monkeypatch, second_category):
    manager, records = isolated_store
    prompts = []

    def classify(prompt, **kwargs):
        assert not vs.vector_lock.locked() and not vs.memory_lock.locked()
        prompts.append(prompt)
        return SimpleNamespace(text=json.dumps({"duplicate_id": "0"}))

    monkeypatch.setattr(gemini, "safe_gemini_call", classify)
    assert manager.save("fact", fact="[USER_FACT]: Ο Λάζαρος από την επόμενη εβδομάδα έχει απογευματινή βάρδια στη δουλειά.",
                        category="work", agent_name="Tool_save_to_memory", time_scope="2026-10-04")
    assert manager.save("fact", fact="[USER_FACT] Starting the week of 2026-10-05, Lazaros is on the afternoon shift at work.",
                        category=second_category, agent_name="Chat_Agent", time_scope="2026-10-05") is False
    assert len(records) == 1
    assert len(vs.get_profile_facts()) == 1
    assert len(prompts) == 1
    assert "2026-10-05" in prompts[0] and "time_scope" in prompts[0]


def test_tool_then_real_sifter_keeps_one_persisted_fact(isolated_store, monkeypatch):
    """Run the actual slow-sifter orchestration through the canonical save manager."""
    manager, records = isolated_store
    user = "Από την επόμενη εβδομάδα έχω απογευματινή βάρδια στη δουλειά"
    acknowledgement = "Σημειώθηκε. Καλή δύναμη με τις απογευματινές βάρδιες από αύριο."
    monkeypatch.setattr(sm, "memory", manager)
    monkeypatch.setattr(gemini, "safe_gemini_call",
                        lambda *a, **k: SimpleNamespace(text='{"duplicate_id": "0"}'))
    monkeypatch.setattr(sm, "safe_gemini_call", lambda *a, **k: SimpleNamespace(text=json.dumps([
        {"fact": "[USER_FACT] Starting the week of 2026-10-05, Lazaros is on the afternoon shift at work.",
         "category": "lazaros", "time_scope": "2026-10-05"}
    ])))
    assert manager.save("fact", fact=f"[USER_FACT]: Ο Λάζαρος {user.lower()}.",
                        category="work", agent_name="Tool_save_to_memory", time_scope="2026-10-04")
    sm.run_memory_sifter_slow(user, acknowledgement, "Chat_Agent", "web")
    assert len(records) == 1
    assert len(vs.get_profile_facts()) == 1
    assert all(acknowledgement not in row["text"] for row in records)


@pytest.mark.parametrize("answer", ['{"duplicate_id": null}', 'invalid JSON'])
def test_distinct_weeks_or_uncertain_comparison_preserve_both(isolated_store, monkeypatch, answer):
    manager, records = isolated_store
    monkeypatch.setattr(gemini, "safe_gemini_call", lambda *a, **k: SimpleNamespace(text=answer))
    for week in ("2026-10-05", "2026-10-12"):
        assert manager.save("fact", fact=f"[USER_FACT] Starting the week of {week}, Lazaros works afternoons.",
                            category="lazaros", agent_name="Chat_Agent", time_scope=week)
    assert len(records) == 2
    assert len(vs.get_profile_facts()) == 2


@pytest.mark.parametrize("change", ["text", "period", "deleted"])
def test_changed_record_during_classification_is_not_suppressed(isolated_store, monkeypatch, change):
    manager, records = isolated_store
    assert manager.save("fact", fact="[USER_FACT] Lazaros works afternoons starting 2026-10-05.",
                        category="work", agent_name="tool")

    def classify(*args, **kwargs):
        if change == "text":
            records[0]["text"] = "[USER_FACT] This is now a different event."
        elif change == "period":
            records[0]["meta"]["time_scope"] = "2026-10-12"
        else:
            records.clear()
        return SimpleNamespace(text='{"duplicate_id": "0"}')

    monkeypatch.setattr(gemini, "safe_gemini_call", classify)
    assert manager.save("fact", fact="[USER_FACT] Ο Λάζαρος δουλεύει απόγευμα από 2026-10-05.",
                        category="lazaros", agent_name="sifter")
    assert len(records) == (1 if change == "deleted" else 2)


@pytest.mark.parametrize("answer", ['{"duplicate_id": "not-supplied"}', '{"duplicate_id": []}', 'failure'])
def test_failed_or_invalid_model_cannot_suppress_fact(isolated_store, monkeypatch, answer):
    manager, records = isolated_store
    assert manager.save("fact", fact="[USER_FACT] First fact on 2026-10-05.",
                        category="work", agent_name="tool")

    def classify(*args, **kwargs):
        if answer == "failure":
            raise RuntimeError("Synthetic provider failure")
        return SimpleNamespace(text=answer)

    monkeypatch.setattr(gemini, "safe_gemini_call", classify)
    assert manager.save("fact", fact="[USER_FACT] Different fact on 2026-10-12.",
                        category="lazaros", agent_name="sifter")
    assert len(records) == 2
