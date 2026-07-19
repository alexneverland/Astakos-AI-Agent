import json

from astakos_skills import recipe_expert


def test_log_meal_blocks_similar_same_day(tmp_path, monkeypatch):
    history_file = tmp_path / "food_history.json"
    history_file.write_text(
        json.dumps(
            [
                {
                    "name": "Μπριζόλες λαιμού με πατάτες τηγανιτές",
                    "date": "2026-06-07 12:00",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(recipe_expert, "HISTORY_FILE", str(history_file))
    monkeypatch.setattr(recipe_expert, "datetime", _FixedDateTime)

    result = recipe_expert.log_meal.func("Μπριζόλες λαιμού με τηγανητές πατάτες")
    data = json.loads(history_file.read_text(encoding="utf-8"))

    assert "ΗΔΗ καταγραφεί" in result
    assert len(data) == 1


def test_log_meal_allows_similar_on_different_day(tmp_path, monkeypatch):
    history_file = tmp_path / "food_history.json"
    history_file.write_text(
        json.dumps(
            [
                {
                    "name": "Μπριζόλες λαιμού με πατάτες τηγανιτές",
                    "date": "2026-06-05 12:00",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(recipe_expert, "HISTORY_FILE", str(history_file))
    monkeypatch.setattr(recipe_expert, "datetime", _FixedDateTime)

    result = recipe_expert.log_meal.func("Μπριζόλες λαιμού με τηγανητές πατάτες")
    data = json.loads(history_file.read_text(encoding="utf-8"))

    assert "καταγράφηκε επιτυχώς" in result
    assert len(data) == 2


def test_log_meal_blocks_same_meal_from_previous_day_leftovers(tmp_path, monkeypatch):
    history_file = tmp_path / "food_history.json"
    history_file.write_text(
        json.dumps(
            [
                {
                    "name": "φακές",
                    "date": "2026-06-06 20:00",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(recipe_expert, "HISTORY_FILE", str(history_file))
    monkeypatch.setattr(recipe_expert, "datetime", _FixedDateTime)

    result = recipe_expert.log_meal.func("φακές")
    data = json.loads(history_file.read_text(encoding="utf-8"))

    assert "ΗΔΗ καταγραφεί" in result
    assert len(data) == 1


class _FixedDateTime:
    @classmethod
    def now(cls):
        from datetime import datetime

        return datetime(2026, 6, 7, 13, 15)

    @classmethod
    def strptime(cls, value, fmt):
        from datetime import datetime

        return datetime.strptime(value, fmt)

def test_recipe_expert_saves_named_recipe(monkeypatch):
    class MockResponse:
        content = "Here is your recipe: *Carbonara*"

    def mock_invoke(*args, **kwargs):
        return MockResponse()

    saved_calls = []
    def mock_save(name, content):
        saved_calls.append((name, content))
        return {"id": "123", "name": name, "content": content}

    monkeypatch.setattr(type(recipe_expert.llm), "invoke", mock_invoke)
    monkeypatch.setattr(recipe_expert, "save_generated_recipe", mock_save)

    result = recipe_expert.recipe_expert.func(
        query="I want carbonara",
        user_context="",
        ingredients="",
        recipe_name="Carbonara"
    )

    assert len(saved_calls) == 1
    assert saved_calls[0][0] == "Carbonara"
    assert "Here is your recipe: *Carbonara*" in saved_calls[0][1]
    assert "[SYSTEM_INSTRUCTION" in result

def test_recipe_expert_returns_text_on_save_failure(monkeypatch):
    class MockResponse:
        content = "Here is your recipe: *Failed Save*"

    def mock_invoke(*args, **kwargs):
        return MockResponse()

    def mock_save(name, content):
        from astakos_skills.recipe_library import RecipeLibraryError
        raise RecipeLibraryError("Mock error")

    monkeypatch.setattr(type(recipe_expert.llm), "invoke", mock_invoke)
    monkeypatch.setattr(recipe_expert, "save_generated_recipe", mock_save)

    result = recipe_expert.recipe_expert.func(
        query="I want carbonara",
        user_context="",
        ingredients="",
        recipe_name="Carbonara"
    )

    assert "Here is your recipe: *Failed Save*" in result
    assert "[SYSTEM_INSTRUCTION" in result
