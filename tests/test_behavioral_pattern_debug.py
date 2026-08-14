from pathlib import Path

from fastapi.testclient import TestClient

from api.server import LOCAL_TOKEN, server


def _event(event_date: str) -> dict[str, str]:
    return {
        "event_type": "meal",
        "category": "food",
        "subject": "user",
        "item": "pasta",
        "status": "consumed",
        "event_date": event_date,
        "record_state": "confirmed",
    }


def test_debug_behavioral_patterns_exposes_read_only_confirmed_candidates(monkeypatch):
    requested_states: list[str | None] = []

    def fake_list_events(*, record_state=None, initialize=True):
        requested_states.append((record_state, initialize))
        return [
            _event("2026-08-01"),
            _event("2026-08-04"),
            _event("2026-08-07"),
        ]

    monkeypatch.setattr("memory.behavioral_event_state.list_events", fake_list_events)
    client = TestClient(server)

    response = client.get(
        "/debug/behavioral-patterns",
        headers={"Authorization": f"Bearer {LOCAL_TOKEN}"},
    )

    assert response.status_code == 200
    assert requested_states == [("confirmed", False)]
    assert response.json() == {
        "candidates": [{
            "event_type": "meal",
            "category": "food",
            "subject": "user",
            "item": "pasta",
            "status": "consumed",
            "occurrence_count": 3,
            "first_date": "2026-08-01",
            "last_date": "2026-08-07",
        }],
        "count": 1,
    }


def test_debug_behavioral_patterns_surfaces_storage_errors(monkeypatch):
    def broken_list_events(*, record_state=None, initialize=True):
        raise RuntimeError("missing behavioral schema")

    monkeypatch.setattr("memory.behavioral_event_state.list_events", broken_list_events)
    client = TestClient(server)

    response = client.get(
        "/debug/behavioral-patterns",
        headers={"Authorization": f"Bearer {LOCAL_TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json()["candidates"] == []
    assert response.json()["count"] == 0
    assert "error" in response.json()


def test_debug_dashboard_fetches_and_renders_behavioral_patterns():
    dashboard = (Path(__file__).parents[1] / "api" / "debug_dashboard.html").read_text(
        encoding="utf-8",
    )

    assert 'id="behavioral-patterns-section"' in dashboard
    assert "fetch('/debug/behavioral-patterns')" in dashboard
    assert "renderBehavioralPatterns" in dashboard
    assert "renderBehavioralPatternLoadError" in dashboard
    assert "pj.error" in dashboard
    assert "BEHAVIORAL_PATTERNS_REFRESH = 60000" in dashboard
    assert "behavioralPatternsFetchInFlight" in dashboard
    assert "enhanceRenderedDashboard(container);" in dashboard
    assert "async function fetchData(forceBehavioralPatterns = false)" in dashboard
    assert "await fetchBehavioralPatterns(forceBehavioralPatterns);" in dashboard
    assert "fetchData(true)" in dashboard
    error_card = dashboard[
        dashboard.index("function renderBehavioralPatternLoadError"):
        dashboard.index("function renderBehavioralPatterns")
    ]
    assert "Load error:" in error_card
    assert "enhanceRenderedDashboard(container);" in error_card
