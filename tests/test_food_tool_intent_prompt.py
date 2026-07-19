from pathlib import Path


def test_food_context_does_not_trigger_meal_logging():
    prompt = (
        Path(__file__).resolve().parents[1] / "core" / "prompts.md"
    ).read_text(encoding="utf-8")

    assert (
        "do not turn it into a recipe or meal-logging intent" in prompt
    )
    assert (
        "explicitly asks to record the meal in history" in prompt
    )
    assert (
        "chose, cooked, ate, or has leftovers from a meal is context only"
        in prompt
    )
    assert '"we ate"' not in prompt
