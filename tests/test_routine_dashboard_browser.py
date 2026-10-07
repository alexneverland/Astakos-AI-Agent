"""Offline browser verification: synthetic state, no credentials or live endpoints."""
from pathlib import Path

import pytest


def test_routine_feedback_debug_in_isolated_browser(tmp_path):
    """Render actual dashboard at multiple widths without accessing live data."""
    playwright = pytest.importorskip("playwright.sync_api")
    html = (Path(__file__).parents[1] / "api" / "debug_dashboard.html").read_text(encoding="utf-8")
    routine = {"id": 11, "day": "Everyday", "time": "09:00", "event": "Synthetic routine",
        "state": "active", "confidence": 1, "conditions": [], "condition_eval": True,
        "cooldown_hours": 0, "effective_cooldown_hours": 4, "cooldown_remaining_h": 3,
        "last_outcome_label": "Skipped: cooldown", "last_outcome_reason": "cooldown",
        "last_condition_check_action": "routine_condition_allowed",
        "feedback_diagnostics": {"status": "recorded", "derived_cooldown_hours": 20,
            "unanswered_streak": 2, "refusal_streak": 0,
            "today": {"date": "2026-10-07", "feedback": "acknowledge"}}}
    runtime = {"routines": {"active": [routine]}, "scheduler": {"jobs": []}}
    errors = []
    with playwright.sync_playwright() as driver:
        try:
            browser = driver.chromium.launch(channel="chrome", headless=True)
        except playwright.Error as exc:
            pytest.skip(f"Installed Chrome unavailable: {type(exc).__name__}")
        try:
            page = browser.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))

            def respond(route):
                """Fulfill every request locally; accidental outbound access is impossible."""
                url = route.request.url
                if url == "http://routine-debug.test/":
                    route.fulfill(content_type="text/html", body=html)
                elif url.endswith("chart.umd.min.js"):
                    route.fulfill(content_type="application/javascript",
                        body="window.Chart=class {constructor(){} destroy(){} update(){}};")
                elif "/debug/runtime" in url:
                    route.fulfill(json=runtime)
                else:
                    route.fulfill(json={"goals": [], "reflections": [], "events": [],
                        "traces": [], "candidates": [], "summary": {}, "initiative": {}})

            page.route("**/*", respond)
            page.goto("http://routine-debug.test/", wait_until="networkidle")
            for width in (320, 768, 1024, 1440):
                page.set_viewport_size({"width": width, "height": 1000})
                playwright.expect(page.get_by_text("Last recorded decision: Skipped: cooldown", exact=True)).to_be_visible()
                playwright.expect(page.get_by_text("Latest condition check: passed — not proof of delivery", exact=True)).to_be_visible()
                playwright.expect(page.get_by_text("Stored: 0h · Scheduler: 4h", exact=True)).to_be_visible()
                playwright.expect(page.get_by_text("Staged policy preview — not the current dispatch gate", exact=True)).to_be_visible()
                page.screenshot(path=str(tmp_path / f"routine-debug-{width}.png"), full_page=True)
            assert errors == []
        finally:
            browser.close()
