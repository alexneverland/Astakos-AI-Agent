"""Offline acceptance coverage for read-only, time-aware routine evidence."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import socket
import json
from zoneinfo import ZoneInfo

import pytest


ATHENS = ZoneInfo("Europe/Athens")
NOW = datetime(2026, 10, 6, 14, tzinfo=ATHENS)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail loudly if evidence evaluation attempts any outbound connection."""
    def blocked(*args, **kwargs):
        raise AssertionError("Evidence tests must stay offline")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


def observation(value="true", recorded_at=None, expires_at="2026-10-06"):
    """Build a persistence record without touching a database."""
    return {"value": value, "updated_at": recorded_at or NOW.isoformat(),
            "expires_at": expires_at}


@pytest.mark.parametrize("value,expected", [("true", True), ("false", False),
                                          (True, True), (False, False)])
def test_recent_stored_boolean_is_preserved(value, expected):
    from services.routine_context_evidence import evaluate_stored_evidence
    result = evaluate_stored_evidence(observation(value), now=NOW)
    assert result.effective_value is expected
    assert result.stored_value is expected
    assert result.status == "known" and result.reason == "fresh"
    assert result.source == "stored_context"


@pytest.mark.parametrize("seconds,known", [(7199, True), (7200, False), (10800, False)])
def test_park_observation_expires_without_becoming_home(seconds, known):
    from services.routine_context_evidence import evaluate_stored_evidence
    record = observation(recorded_at=(NOW - timedelta(seconds=seconds)).isoformat())
    before = deepcopy(record)
    result = evaluate_stored_evidence(record, now=NOW)
    assert result.effective_value is (True if known else None)
    assert result.reason == ("fresh" if known else "stale")
    assert result.stored_value is True and record == before
    assert result.age_seconds == seconds


@pytest.mark.parametrize("record,reason", [
    (None, "missing"), ({}, "invalid_value"),
    (observation("yes"), "invalid_value"), (observation(1), "invalid_value"),
    ({"value": "true"}, "invalid_timestamp"),
    (observation(recorded_at="bad-date"), "invalid_timestamp"),
    (observation(recorded_at="2026-10-06"), "invalid_timestamp"),
    (observation(recorded_at=(NOW + timedelta(seconds=1)).isoformat()), "future_timestamp"),
    (observation(expires_at="2026-10-05"), "expired"),
    (observation(expires_at="not-a-date"), "invalid_expiry"),
])
def test_unusable_records_remain_unknown(record, reason):
    from services.routine_context_evidence import evaluate_stored_evidence
    result = evaluate_stored_evidence(record, now=NOW)
    assert result.effective_value is None and result.status == "unknown"
    assert result.reason == reason


@pytest.mark.parametrize("stamp", ["2026-10-06T13:30:00", "2026-10-06 13:30:00",
                                   "2026-10-06T10:30:00+00:00"])
def test_naive_local_and_aware_timestamps_represent_same_instant(stamp):
    from services.routine_context_evidence import evaluate_stored_evidence
    result = evaluate_stored_evidence(observation(recorded_at=stamp), now=NOW)
    assert result.age_seconds == 1800
    assert result.recorded_at.timestamp() == datetime(2026, 10, 6, 13, 30, tzinfo=ATHENS).timestamp()


def test_date_expiry_is_next_local_midnight():
    from services.routine_context_evidence import evaluate_stored_evidence
    now = datetime(2026, 10, 6, 23, 59, tzinfo=ATHENS)
    record = observation(recorded_at=now.isoformat())
    assert evaluate_stored_evidence(record, now=now).valid_until == datetime(2026, 10, 7, tzinfo=ATHENS)
    assert evaluate_stored_evidence(record, now=now + timedelta(minutes=1)).reason == "expired"


def test_dst_fallback_uses_elapsed_time_not_wall_clock():
    from services.routine_context_evidence import evaluate_stored_evidence
    start = datetime(2026, 10, 25, 3, 30, tzinfo=ATHENS, fold=0)
    now = datetime(2026, 10, 25, 4, 30, tzinfo=ATHENS)
    result = evaluate_stored_evidence(observation(recorded_at=start.isoformat(), expires_at=None), now=now)
    assert result.age_seconds == 7200 and result.reason == "stale"


def test_dst_midnight_expiry_uses_calendar_date_not_24_hours():
    from services.routine_context_evidence import evaluate_stored_evidence
    now = datetime(2026, 10, 25, 23, 45, tzinfo=ATHENS)
    result = evaluate_stored_evidence(observation(recorded_at=now.isoformat(), expires_at="2026-10-25"), now=now)
    assert result.valid_until == datetime(2026, 10, 26, tzinfo=ATHENS)


@pytest.mark.parametrize("stamp", ["2026-10-25T03:30:00", "2026-03-29T03:30:00"])
def test_ambiguous_or_nonexistent_legacy_time_is_not_guessed(stamp):
    from services.routine_context_evidence import evaluate_stored_evidence
    now = datetime(2026, 10, 25, 4, tzinfo=ATHENS)
    result = evaluate_stored_evidence(observation(recorded_at=stamp, expires_at=None), now=now)
    assert result.reason == "invalid_timestamp" and result.effective_value is None


def test_naive_evaluation_time_is_rejected():
    from services.routine_context_evidence import evaluate_stored_evidence
    with pytest.raises(ValueError, match="timezone"):
        evaluate_stored_evidence(observation(), now=NOW.replace(tzinfo=None))


def gps_point(seconds_old=0, **overrides):
    """Build a recent owner-location observation, not family presence."""
    return {"lat": 40.0, "lon": 23.0, "timestamp": NOW.timestamp() - seconds_old, **overrides}


@pytest.mark.parametrize("seconds,known", [(899, True), (900, False), (14400, False)])
def test_gps_freshness_has_exact_fifteen_minute_boundary(seconds, known):
    from services.routine_context_evidence import evaluate_gps_evidence
    result = evaluate_gps_evidence(gps_point(seconds), now=NOW, location_resolver=lambda lat, lon: True)
    assert result.effective_value is (False if known else None)
    assert result.reason == ("fresh" if known else "stale")
    assert result.age_seconds == seconds


@pytest.mark.parametrize("point,reason", [
    (None, "missing"), ([], "invalid_point"),
    (gps_point(lat=91), "invalid_point"), (gps_point(lon=181), "invalid_point"),
    (gps_point(lat=float("nan")), "invalid_point"),
    (gps_point(lat=True), "invalid_point"), (gps_point(lat="not-coordinates"), "invalid_point"),
    (gps_point(timestamp=float("inf")), "invalid_timestamp"),
    (gps_point(timestamp=True), "invalid_timestamp"),
    (gps_point(timestamp=0), "invalid_timestamp"),
    (gps_point(timestamp=NOW.timestamp() + 1), "future_timestamp"),
])
def test_invalid_gps_cannot_establish_home(point, reason):
    from services.routine_context_evidence import evaluate_gps_evidence
    def never_called(lat, lon):
        raise AssertionError("Invalid GPS must not reach geometry")
    result = evaluate_gps_evidence(point, now=NOW, location_resolver=never_called)
    assert result.status == "unknown" and result.reason == reason


@pytest.mark.parametrize("geometry", [None, 1, "home"])
def test_unusable_home_geometry_is_unknown(geometry):
    from services.routine_context_evidence import evaluate_gps_evidence
    result = evaluate_gps_evidence(gps_point(), now=NOW, location_resolver=lambda lat, lon: geometry)
    assert result.reason == "invalid_geometry" and result.effective_value is None


def test_geometry_read_error_remains_unknown_without_exception_text():
    from services.routine_context_evidence import evaluate_gps_evidence
    def broken(lat, lon):
        raise RuntimeError("private diagnostic must not appear")
    result = evaluate_gps_evidence(gps_point(), now=NOW, location_resolver=broken)
    assert result.reason == "read_error" and "private" not in repr(result)


def test_home_gps_does_not_invent_family_presence():
    from services.routine_context_evidence import evaluate_context_evidence
    records = {"user_out_of_home": observation(recorded_at=(NOW - timedelta(hours=3)).isoformat())}
    point = gps_point()
    before = deepcopy((records, point))
    result = evaluate_context_evidence(records, point, now=NOW, location_resolver=lambda lat, lon: True)
    assert result["user_out_of_home"].effective_value is False
    assert result["user_out_of_home"].source == "gps"
    assert result["user_out_of_home"].stored_value is True
    for key in ("family_at_home", "partner_with_user", "kid1_with_user", "kid1_with_partner"):
        assert result[key].effective_value is None
    assert (records, point) == before


@pytest.mark.parametrize("at_home", [True, False])
def test_conflicting_recent_gps_and_stored_whereabouts_are_unknown(at_home):
    from services.routine_context_evidence import evaluate_context_evidence
    result = evaluate_context_evidence({"user_out_of_home": observation(at_home)}, gps_point(),
                                      now=NOW, location_resolver=lambda lat, lon: at_home)
    assert result["user_out_of_home"].effective_value is None
    assert result["user_out_of_home"].source == "conflict"
    assert result["user_out_of_home"].reason == "conflict"


def test_agreement_and_stale_gps_do_not_overrule_recent_stored_whereabouts():
    from services.routine_context_evidence import evaluate_context_evidence
    for point in (gps_point(), gps_point(900)):
        result = evaluate_context_evidence({"user_out_of_home": observation(False)}, point,
                                          now=NOW, location_resolver=lambda lat, lon: True)
        assert result["user_out_of_home"].effective_value is False
        assert result["user_out_of_home"].source == "stored_context"


def test_owner_away_conflicts_with_household_home_but_not_partner_copresence():
    from services.routine_context_evidence import evaluate_context_evidence
    records = {"family_at_home": observation(True), "partner_with_user": observation(True)}
    result = evaluate_context_evidence(records, gps_point(), now=NOW, location_resolver=lambda lat, lon: False)
    assert result["user_out_of_home"].effective_value is True
    assert result["family_at_home"].effective_value is None
    assert result["family_at_home"].reason == "conflict"
    assert result["partner_with_user"].effective_value is True


def test_conflicting_owner_candidates_cannot_support_household_home():
    from services.routine_context_evidence import evaluate_context_evidence
    result = evaluate_context_evidence({"user_out_of_home": observation(False), "family_at_home": observation(True)},
                                      gps_point(), now=NOW, location_resolver=lambda lat, lon: False)
    assert result["user_out_of_home"].reason == "conflict"
    assert result["family_at_home"].reason == "conflict"


def test_public_snapshot_uses_loaders_once_and_does_not_touch_unscoped_state():
    from services.routine_context import build_routine_context_evidence
    records = {"partner_with_user": observation(False)}
    read_keys, gps_reads = [], []
    def reader(key):
        read_keys.append(key)
        return records.get(key)
    def gps_loader():
        gps_reads.append(True)
        return gps_point()
    result = build_routine_context_evidence(NOW, state_reader=reader, gps_loader=gps_loader,
                                           location_resolver=lambda lat, lon: True)
    assert set(read_keys) == set(result) and len(read_keys) == 5
    assert len(gps_reads) == 1
    assert result["partner_with_user"].effective_value is False
    assert result["user_out_of_home"].effective_value is False
    assert "current_shift" not in result and "kid1_absence_scope" not in result


def test_read_failures_do_not_invent_state_or_expose_diagnostics():
    from services.routine_context import build_routine_context_evidence
    def broken(*args):
        raise OSError("private filename")
    result = build_routine_context_evidence(NOW, state_reader=broken, gps_loader=broken,
                                           location_resolver=broken)
    assert all(item.status == "unknown" and item.reason == "read_error" for item in result.values())
    assert "private" not in repr(result)


def test_fresh_gps_can_supply_owner_state_after_context_read_failure():
    from services.routine_context import build_routine_context_evidence
    def broken(key):
        raise OSError("unavailable")
    result = build_routine_context_evidence(NOW, state_reader=broken, gps_loader=lambda: gps_point(),
                                           location_resolver=lambda lat, lon: False)
    assert result["user_out_of_home"].effective_value is True
    assert result["partner_with_user"].reason == "read_error"


def test_gps_read_failure_does_not_overrule_known_context():
    from services.routine_context import build_routine_context_evidence
    def broken():
        raise OSError("unavailable")
    result = build_routine_context_evidence(NOW, state_reader=lambda key: observation(False),
                                           gps_loader=broken, location_resolver=lambda lat, lon: True)
    assert result["user_out_of_home"].effective_value is False


def test_default_wiring_uses_temporary_storage_and_canonical_home_geometry(monkeypatch, tmp_path):
    import memory.routine_db as db
    import services.routine_context as rc
    import config
    from services.location_update import location_is_home
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "routines.db"))
    db.setup_db()
    db.set_context_state("partner_with_user", "false")
    db.set_context_state("current_shift", "afternoon")
    db.set_context_state("kid1_absence_scope", "extended")
    records = {key: db.get_context_state(key) for key in
               ("partner_with_user", "current_shift", "kid1_absence_scope")}
    stamp = datetime.fromisoformat(records["partner_with_user"]["updated_at"]).replace(tzinfo=ATHENS)
    point = {"lat": 40.0, "lon": 23.0, "timestamp": stamp.timestamp()}
    gps_file = tmp_path / "location.json"
    gps_file.write_text(json.dumps(point), encoding="utf-8")
    original_bytes = gps_file.read_bytes()
    monkeypatch.setattr(rc, "GPS_STORAGE_FILE", str(gps_file))
    monkeypatch.setattr(config, "HOME_COORDS", (40.0, 23.0))
    monkeypatch.setattr(config, "HOME_RADIUS_M", 100)
    assert location_is_home(40.0, 23.0) is True
    def forbidden_write(*args, **kwargs):
        raise AssertionError("Evidence must not write context state")
    monkeypatch.setattr(db, "set_context_state", forbidden_write)
    result = rc.build_routine_context_evidence(stamp)
    assert result["user_out_of_home"].effective_value is False
    assert result["user_out_of_home"].source == "gps"
    assert result["partner_with_user"].effective_value is False
    assert result["family_at_home"].effective_value is None
    assert gps_file.read_bytes() == original_bytes
    assert {key: db.get_context_state(key) for key in records} == records
    assert rc.resolve_current_shift(stamp) == ("afternoon" if stamp.weekday() < 5 else "off")
    assert rc.resolve_kid1_absence_scope(stamp) == "extended"


@pytest.mark.parametrize("contents,reason", [("{broken", "read_error"), ("[]", "invalid_point"),
                                          (" " * 8200, "read_error")])
def test_default_gps_loader_rejects_malformed_or_oversized_files(monkeypatch, tmp_path, contents, reason):
    import services.routine_context as rc
    path = tmp_path / "location.json"
    path.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(rc, "GPS_STORAGE_FILE", str(path))
    result = rc.build_routine_context_evidence(NOW, state_reader=lambda key: None)
    assert result["user_out_of_home"].reason == reason
    assert result["user_out_of_home"].effective_value is None
