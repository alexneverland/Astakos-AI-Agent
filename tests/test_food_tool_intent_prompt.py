from pathlib import Path


def test_food_context_does_not_trigger_meal_logging():
    prompt = (
        Path(__file__).resolve().parents[1] / "core" / "prompts.md"
    ).read_text(encoding="utf-8")

    assert (
        "do not turn it into a recipe or meal-logging intent" in prompt
    )
    assert (
        "directly reports that he ate or cooked a named meal" in prompt
    )
    assert "Do this silently: do not ask for approval" in prompt
    assert "food mentioned only as general context" in prompt
