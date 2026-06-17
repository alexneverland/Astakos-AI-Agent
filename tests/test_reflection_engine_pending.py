import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _set_temp_db(monkeypatch, tmp_path):
    import services.reflection_engine as ref_eng

    db_path = tmp_path / "reflections_test.db"
    monkeypatch.setattr(ref_eng, "DB_PATH", str(db_path))
    ref_eng._ensure_table()
    return ref_eng


def test_pending_reflection_blocks_duplicate_creation(monkeypatch, tmp_path):
    re = _set_temp_db(monkeypatch, tmp_path)

    re._save_reflection(
        source="routine",
        observation="Το πάρκο αγνοείται συχνά",
        action="increase_cooldown",
        confidence=0.62,
        lesson="Ίσως είναι πολύ συχνό.",
        applied=False,
        routine_id=12,
        action_value=48,
    )

    assert re._already_reflected(
        "Το πάρκο αγνοείται συχνά",
        "increase_cooldown",
        routine_id=12,
        action_value=48,
    ) is True


def test_load_pending_reflections_ignores_applied_and_rejected(monkeypatch, tmp_path):
    re = _set_temp_db(monkeypatch, tmp_path)

    pending_id = re._save_reflection(
        source="routine",
        observation="Το πάρκο αγνοείται συχνά",
        action="increase_cooldown",
        confidence=0.62,
        lesson="Ίσως είναι πολύ συχνό.",
        applied=False,
        routine_id=12,
        action_value=48,
    )
    applied_id = re._save_reflection(
        source="routine",
        observation="Το ξυπνητήρι πέτυχε",
        action="reduce_frequency",
        confidence=0.91,
        lesson="Καλά ρυθμισμένο.",
        applied=True,
        routine_id=13,
        action_value=None,
    )
    rejected_id = re._save_reflection(
        source="routine",
        observation="Μην αλλάξεις την ώρα στο πάρκο",
        action="change_time",
        confidence=0.64,
        lesson="Ο χρήστης δεν το θέλει.",
        applied=False,
        routine_id=14,
        action_value="18:00",
    )
    re.mark_reflection_rejected(rejected_id)

    loaded = re.load_pending_reflections()

    assert pending_id in loaded
    assert applied_id not in loaded
    assert rejected_id not in loaded
    assert loaded[pending_id]["routine_id"] == 12
    assert loaded[pending_id]["action_value"] == "48"
