"""Regression coverage for Home_Agent conversational safety instructions."""


def test_home_agent_prompt_handles_ambiguous_short_continuations() -> None:
    """Brief follow-ups must not revive completed actions from visible history."""
    from core.utils import load_agent_prompt

    prompt = load_agent_prompt("Home_Agent")

    assert "one recent, unresolved local action" in prompt
    assert "Do not reopen routines, reminders, or other actions that were already completed" in prompt
    assert "ask a concise clarification before calling a write or control tool" in prompt
