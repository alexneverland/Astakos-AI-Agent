from unittest.mock import patch

import memory.working_memory as wm


class _FakeResponse:
    def __init__(self, content):
        self.content = content


def test_validate_working_memory_tags_accepts_short_tags():
    result = wm._validate_working_memory_tags("Refactoring, Docker Auth Fix")
    assert result == "Refactoring, Docker Auth Fix"


def test_validate_working_memory_tags_rejects_reasoning_dump():
    result = wm._validate_working_memory_tags(
        "I think the user is currently working on refactoring because he mentioned Docker auth and web UI issues."
    )
    assert result == ""


def test_update_working_memory_does_not_save_reasoning_dump():
    fake_response = _FakeResponse(
        "I think the user is currently working on refactoring because he mentioned Docker auth and web UI issues."
    )

    with patch("memory.working_memory.safe_llm_invoke", return_value=fake_response), \
         patch("memory.working_memory.memory.save") as save_mock, \
         patch("memory.working_memory.load_agent_prompt", return_value="{user_context}\n{ai_context}"):
        wm.update_working_memory("hello", "hi")

    save_mock.assert_not_called()


def test_update_working_memory_saves_valid_tags():
    fake_response = _FakeResponse("Refactoring, Docker Auth Fix")

    with patch("memory.working_memory.safe_llm_invoke", return_value=fake_response), \
         patch("memory.working_memory.memory.save") as save_mock, \
         patch("memory.working_memory.load_agent_prompt", return_value="{user_context}\n{ai_context}"):
        wm.update_working_memory("hello", "hi")

    save_mock.assert_called_once_with(memory_type="working", new_tags="Refactoring, Docker Auth Fix")


def test_update_working_memory_skips_operational_routine_exchange_before_llm():
    with patch("memory.working_memory.safe_llm_invoke") as llm_mock, \
         patch("memory.working_memory.memory.save") as save_mock:
        wm.update_working_memory(
            "ρουτινα σχολασμα από τη δουλειά μονο οταν ειμαι πρωινη βαρδια και μονο οταν ειμαι στην δουλεια",
            "⚙️ Η ρουτίνα 'σχόλασμα από τη δουλειά' απέκτησε condition: shift_mode (allow_when_true).",
        )

    llm_mock.assert_not_called()
    save_mock.assert_not_called()


def test_operational_guard_uses_external_routine_admin_markers(monkeypatch) -> None:
    """Ensure routine administration detection follows configured marker lists."""
    monkeypatch.setattr(
        "memory.working_memory.nl_config.WM_ROUTINE_REFERENCE_MARKERS",
        ("configured routine",),
    )
    monkeypatch.setattr(
        "memory.working_memory.nl_config.WM_ROUTINE_ADMIN_MARKERS",
        ("configured admin",),
    )
    monkeypatch.setattr(
        "memory.working_memory.nl_config.WM_OPERATIONAL_AI_MARKERS",
        ("configured ai marker",),
    )

    assert wm._looks_like_operational_working_memory_exchange(
        "configured routine configured admin",
        "normal response",
    ) is True
    assert wm._looks_like_operational_working_memory_exchange(
        "normal user message",
        "configured ai marker",
    ) is True


# ════════════════════════════════════════════════════════════════
# Regression tests for colon-in-tags bug fix (2026-07-25)
# The banned marker `": "` was removed because it rejected valid
# tags like "Shopping: Apple Watch". These tests lock the fix.
# ════════════════════════════════════════════════════════════════

def test_validate_tags_accepts_colon_in_tag():
    """Tags with colons (e.g. 'Shopping: Apple Watch') must pass.
    This was the exact bug — the `': '` banned marker rejected them."""
    result = wm._validate_working_memory_tags("Shopping: Apple Watch, Checking store hours")
    assert result == "Shopping: Apple Watch, Checking store hours"


def test_validate_tags_accepts_multiple_colon_tags():
    """Multiple colon-containing tags must pass."""
    result = wm._validate_working_memory_tags("Task: coding, Mood: focused")
    assert result == "Task: coding, Mood: focused"


def test_validate_tags_accepts_single_colon_tag():
    """A single colon tag must pass."""
    result = wm._validate_working_memory_tags("Activity: walking")
    assert result == "Activity: walking"


# ════════════════════════════════════════════════════════════════
# Rejection rule regression — ensure all other guards still work
# ════════════════════════════════════════════════════════════════

def test_validate_tags_rejects_empty():
    assert wm._validate_working_memory_tags("") == ""


def test_validate_tags_returns_empty_keyword():
    assert wm._validate_working_memory_tags("EMPTY") == "EMPTY"


def test_validate_tags_rejects_newlines():
    assert wm._validate_working_memory_tags("Shopping\nWalking") == ""


def test_validate_tags_rejects_because():
    assert wm._validate_working_memory_tags("Shopping because he mentioned it") == ""


def test_validate_tags_rejects_the_user():
    assert wm._validate_working_memory_tags("the user is shopping") == ""


def test_validate_tags_rejects_here_are():
    assert wm._validate_working_memory_tags("Here are the tags") == ""


def test_validate_tags_rejects_tags_label():
    assert wm._validate_working_memory_tags("Tags: shopping, walking") == ""


def test_validate_tags_rejects_numbered_list():
    assert wm._validate_working_memory_tags("1. Shopping") == ""


def test_validate_tags_rejects_bullet_list():
    assert wm._validate_working_memory_tags("- Shopping") == ""


def test_validate_tags_rejects_markdown():
    assert wm._validate_working_memory_tags("```code block```") == ""


def test_validate_tags_rejects_more_than_three_tags():
    assert wm._validate_working_memory_tags("a, b, c, d") == ""


def test_validate_tags_rejects_tag_with_too_many_words():
    """Each tag must be ≤ 4 words."""
    assert wm._validate_working_memory_tags("this is a very long tag") == ""


def test_validate_tags_rejects_tag_over_40_chars():
    assert wm._validate_working_memory_tags("a" * 41) == ""


def test_validate_tags_rejects_special_characters():
    assert wm._validate_working_memory_tags("Shopping; walking") == ""
    assert wm._validate_working_memory_tags("Shopping {now}") == ""
    assert wm._validate_working_memory_tags("Shopping [later]") == ""


def test_update_working_memory_saves_colon_tags():
    """End-to-end: tags with colons should be saved to working memory."""
    fake_response = _FakeResponse("Shopping: Apple Watch, Checking store hours")

    with patch("memory.working_memory.safe_llm_invoke", return_value=fake_response), \
         patch("memory.working_memory.memory.save") as save_mock, \
         patch("memory.working_memory.load_agent_prompt", return_value="{user_context}\n{ai_context}"):
        wm.update_working_memory("πάμε για ρολόι Apple Watch", "Πάμε!")

    save_mock.assert_called_once_with(
        memory_type="working",
        new_tags="Shopping: Apple Watch, Checking store hours",
    )
