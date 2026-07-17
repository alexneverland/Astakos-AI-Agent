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
