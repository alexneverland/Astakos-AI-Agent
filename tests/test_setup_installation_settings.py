"""Guided fresh-install settings with temporary files and no provider calls."""
import asyncio
import json
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import HTTPException


@pytest.fixture
def wizard(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    """Isolate wizard writes, diagnostics, channel selection and process exit."""
    from api import setup_wizard
    from core import diagnostics
    monkeypatch.setenv("ASTAKOS_EXTERNAL_CHANNEL", "telegram")
    for attribute, name in {
        "ENV_FILE": ".env", "SETTINGS_FILE": "settings.json", "PERSONA_FILE": "persona.md",
        "INTENTS_FILE": "intents.json", "ROUTINES_FILE": "routines.json", "PROMPTS_DIR": "prompts",
    }.items():
        monkeypatch.setattr(setup_wizard, attribute, str(tmp_path / name))
    monkeypatch.setattr(diagnostics, "get_system_diagnostics_summary", lambda **kwargs: {})

    class NoExitThread:
        """Prevent the wizard exit timer from terminating the test process."""
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass
        def start(self) -> None:
            pass

    monkeypatch.setattr(setup_wizard.threading, "Thread", NoExitThread)
    return setup_wizard


@pytest.mark.parametrize("settings", [
    {"home_coords": [91, 10]},
    {"work_coords": [10]},
    {"home_coords": [float("nan"), 10]},
    {"home_radius_m": -1},
    {"work_radius_m": True},
    {"backup_drive_folder_id": "https://drive.google.com/folders/example"},
])
def test_invalid_guided_settings_fail_before_writes(wizard: ModuleType, settings: dict[str, object], tmp_path: Path) -> None:
    """Malformed location/backup settings cannot leave a half-saved configuration."""
    with pytest.raises(HTTPException) as error:
        asyncio.run(wizard.save_setup(wizard.SetupPayload(basic={"settings": settings}, advanced={}, prompts={})))
    assert error.value.status_code == 422
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / "settings.json").exists()


def test_guided_settings_round_trip_and_clear(wizard: ModuleType, tmp_path: Path) -> None:
    """Location and private backup folder fields survive save/reopen and explicit clearing."""
    settings = {"home_coords": [51.5, -0.1], "home_radius_m": 150,
        "work_coords": [51.6, -0.2], "work_radius_m": 300,
        "backup_drive_folder_id": "fixture_private_folder", "developer_name": "FixtureUser"}
    (tmp_path / "settings.json").write_text(json.dumps({"unrelated": "preserved"}))
    result = asyncio.run(wizard.save_setup(wizard.SetupPayload(basic={"settings": settings}, advanced={}, prompts={})))
    assert result["status"] == "success"
    stored = json.loads((tmp_path / "settings.json").read_text())
    assert all(stored[key] == value for key, value in settings.items())
    assert stored["unrelated"] == "preserved"
    cleared = {"home_coords": [0, 0], "work_coords": [0, 0], "backup_drive_folder_id": ""}
    asyncio.run(wizard.save_setup(wizard.SetupPayload(basic={"settings": cleared}, advanced={}, prompts={})))
    assert json.loads((tmp_path / "settings.json").read_text())["backup_drive_folder_id"] == ""


def test_optional_integrations_preserve_masked_secrets(wizard: ModuleType, tmp_path: Path) -> None:
    """Guided fields save without cloud access and never overwrite masks as secrets."""
    basic = {"github_token": "fixture-github", "vacuum_token": "fixture-vacuum",
             "linkedin_token": "fixture-linkedin", "vacuum_ip": "192.0.2.1",
             "project_id": "fixture-project", "vertex_location": "global",
             "spotify_client_id": "fixture-spotify-id", "spotify_client_secret": "fixture-spotify-secret",
             "spotify_redirect_uri": "http://127.0.0.1:8888/callback", "google_places_api_key": "fixture-places"}
    asyncio.run(wizard.save_setup(wizard.SetupPayload(basic=basic, advanced={}, prompts={})))
    stored = (tmp_path / ".env").read_text()
    for value in basic.values():
        assert value in stored
    visible = asyncio.run(wizard.get_raw_files())["env"]
    for field in ("github_token", "vacuum_token", "linkedin_token", "spotify_client_id",
                  "spotify_client_secret", "google_places_api_key"):
        assert basic[field] not in visible
    masked = {key: "********" for key in ("github_token", "vacuum_token", "linkedin_token",
                                           "spotify_client_id", "spotify_client_secret", "google_places_api_key")}
    asyncio.run(wizard.save_setup(wizard.SetupPayload(basic=masked, advanced={}, prompts={})))
    stored_again = (tmp_path / ".env").read_text()
    assert stored_again == stored
    assert "********" not in stored_again


def test_integration_newline_rejected_before_write(wizard: ModuleType, tmp_path: Path) -> None:
    """A guided value cannot introduce another environment setting."""
    with pytest.raises(HTTPException) as error:
        asyncio.run(wizard.save_setup(wizard.SetupPayload(
            basic={"github_token": "fixture\nOTHER=value"}, advanced={}, prompts={})))
    assert error.value.status_code == 422
    assert not (tmp_path / ".env").exists()


def test_guided_settings_in_offline_browser(tmp_path: Path) -> None:
    """Exercise verified form interactions and capture the exact submitted payload."""
    playwright = pytest.importorskip("playwright.sync_api")
    html = (Path(__file__).parents[1] / "api/static/setup.html").read_text(encoding="utf-8")
    captured: list[dict] = []
    errors: list[str] = []
    raw = {"env": "LLM_PROVIDER=openai\nASTAKOS_EXTERNAL_CHANNEL=telegram\nGITHUB_TOKEN=********",
           "settings": {"user_name": "Fixture", "home_coords": [0, 0], "work_coords": [0, 0],
                        "unrelated": "preserved"},
           "installation": {"officecli": {"present": False, "version": "1.0.154"}}}
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))

            def respond(route: object) -> None:
                """Fulfill every request locally, including third-party styling scripts."""
                url = route.request.url
                if url == "http://setup.test/":
                    route.fulfill(content_type="text/html", body=html)
                elif "cdn.tailwindcss.com" in url:
                    route.fulfill(content_type="application/javascript", body="")
                elif url.endswith("/api/raw_files"):
                    route.fulfill(json=raw)
                elif url.endswith("/api/diagnostics"):
                    route.fulfill(json={"workspace": {}})
                elif url.endswith("/api/setup"):
                    captured.append(route.request.post_data_json)
                    route.fulfill(json={"status": "success"})
                else:
                    pytest.fail(f"Unexpected browser request: {url}")

            page.route("**/*", respond)
            page.goto("http://setup.test/", wait_until="networkidle")
            # Offline CDN substitution keeps visibility semantics; this test
            # checks form behavior, not Tailwind's visual rendering.
            page.add_style_tag(content=".hidden{display:none}svg{width:16px;height:16px}")
            playwright.expect(page.locator("#github_token")).to_have_value("********")
            playwright.expect(page.locator("#officecli_setup_status")).to_contain_text("not found")
            page.locator("#home_latitude").fill("51.5")
            assert page.locator("#home_longitude").evaluate("el => el.required")
            assert not page.locator("#setupForm").evaluate("el => el.checkValidity()")
            page.locator("#home_longitude").fill("-0.1")
            page.locator("#backup_drive_folder_id").fill("fixture_folder")
            page.locator("#developer_name").fill("FixtureDeveloper")
            page.locator("#vertex_location").fill("global")
            page.locator("#google_places_api_key").fill("fixture-places")
            page.locator("#spotify_client_id").fill("fixture-spotify-id")
            page.locator("#spotify_client_secret").fill("fixture-spotify-secret")
            page.locator("#spotify_redirect_uri").fill("http://127.0.0.1:8888/callback")
            for width in (360, 1280):
                page.set_viewport_size({"width": width, "height": 1000})
                playwright.expect(page.locator("#home_latitude")).to_be_visible()
                page.locator("#installation_settings").scroll_into_view_if_needed()
                page.screenshot(path=str(tmp_path / f"wizard-installation-{width}.png"))
            page.locator("#saveBtn").click()
            playwright.expect(page.locator("#successMsg")).to_be_visible()
            assert len(captured) == 1
            settings = captured[0]["basic"]["settings"]
            assert settings["home_coords"] == [51.5, -0.1]
            assert settings["work_coords"] == [0, 0]
            assert settings["backup_drive_folder_id"] == "fixture_folder"
            assert settings["developer_name"] == "FixtureDeveloper"
            assert settings["unrelated"] == "preserved"
            assert captured[0]["basic"]["github_token"] == "********"
            assert captured[0]["basic"]["vertex_location"] == "global"
            assert captured[0]["basic"]["google_places_api_key"] == "fixture-places"
            assert captured[0]["basic"]["spotify_client_id"] == "fixture-spotify-id"
            assert captured[0]["basic"]["spotify_client_secret"] == "fixture-spotify-secret"
            assert captured[0]["basic"]["spotify_redirect_uri"] == "http://127.0.0.1:8888/callback"
            assert errors == []
        finally:
            browser.close()
