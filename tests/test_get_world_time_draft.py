"""Focused tests for the unregistered world-time draft skill."""

from collections.abc import Iterator

import pytest

import core.i18n
from astakos_skills.get_world_time import get_world_time
from core.i18n import load_locale


@pytest.fixture(autouse=True)
def restore_locale() -> Iterator[None]:
    """Restore the active locale after each tool invocation test."""
    original_locale = core.i18n.LANG
    yield
    load_locale(original_locale)


def test_world_time_renders_london_and_tokyo_in_english() -> None:
    """Render successful English results without untranslated placeholders."""
    load_locale("en")

    for city, timezone in (("London", "Europe/London"), ("Tokyo", "Asia/Tokyo")):
        result = get_world_time.invoke({"city": city})
        assert "[world_time_result]" not in result
        assert f"Time in {city}" in result
        assert timezone in result


def test_world_time_renders_greek_result_and_unknown_city() -> None:
    """Render localized Greek success and missing-city responses."""
    load_locale("el")

    result = get_world_time.invoke({"city": "London"})
    assert "[world_time_result]" not in result
    assert "Europe/London" in result

    missing = get_world_time.invoke({"city": "Atlantis"})
    assert "[world_time_not_found]" not in missing

def test_world_time_renders_common_cities() -> None:
    """Test lookup for San Francisco, Mumbai, and exact IANA string."""
    load_locale("en")
    for city, timezone in (
        ("San Francisco", "America/Los_Angeles"),
        ("Mumbai", "Asia/Kolkata"),
        ("Europe/London", "Europe/London"),
    ):
        result = get_world_time.invoke({"city": city})
        assert timezone in result

def test_world_time_diff_is_relative_to_athens(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure time difference is relative to Europe/Athens, not process local time."""
    import datetime
    from zoneinfo import ZoneInfo
    from astakos_skills import get_world_time as gwt_module

    class MockDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            # Fixed point in summer (July)
            return datetime.datetime(2026, 7, 26, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(gwt_module, "datetime", MockDatetime)
    load_locale("en")

    # London is UTC+1 in summer, Athens is UTC+3 in summer.
    # Therefore, diff should be -2.
    result = get_world_time.invoke({"city": "London"})
    assert "(Difference: -2 hours)" in result
