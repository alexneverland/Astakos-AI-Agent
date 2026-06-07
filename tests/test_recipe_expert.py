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
                    "date": "2026-06-06 12:00",
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


class _FixedDateTime:
    @classmethod
    def now(cls):
        from datetime import datetime

        return datetime(2026, 6, 7, 13, 15)
