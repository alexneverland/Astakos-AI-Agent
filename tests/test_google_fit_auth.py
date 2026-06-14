import json

import pytest

from astakos_skills import google_fit


def _write_token(path, scopes):
    path.write_text(json.dumps({"scopes": scopes}), encoding="utf-8")


def test_fit_scope_guard_accepts_classic_fit_scopes(tmp_path, monkeypatch):
    token_path = tmp_path / "token.json"
    _write_token(token_path, google_fit.SCOPES)
    monkeypatch.setattr(google_fit, "TOKEN_PATH", str(token_path))

    google_fit._ensure_fit_token_scopes()


def test_fit_scope_guard_rejects_google_health_token(tmp_path, monkeypatch):
    token_path = tmp_path / "token.json"
    _write_token(
        token_path,
        [
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
            "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
            "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
        ],
    )
    monkeypatch.setattr(google_fit, "TOKEN_PATH", str(token_path))

    with pytest.raises(google_fit.GoogleFitAuthError) as exc:
        google_fit._ensure_fit_token_scopes()

    assert "Google Health" in str(exc.value)
    assert "fitness.activity.read" in str(exc.value)


def test_morning_summary_reports_fit_auth_problem(monkeypatch):
    def fail_auth():
        raise google_fit.GoogleFitAuthError("bad token scopes")

    monkeypatch.setattr(google_fit, "_get_credentials", fail_auth)

    result = google_fit.get_morning_summary()

    assert "Google Fit auth" in result
    assert "bad token scopes" in result
    assert "Βήματα χθες: σφάλμα" not in result
