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
        raise google_fit.GoogleFitAuthError("Google Fit requires additional permissions. Please reconnect Google Workspace.")

    monkeypatch.setattr(google_fit, "_get_credentials", fail_auth)

    result = google_fit.get_morning_summary()

    assert "Google Fit auth" in result
    assert "reconnect Google Workspace" in result
    assert "Βήματα χθες: σφάλμα" not in result


def test_morning_summary_does_not_leak_raw_oauth_secret_or_exception(monkeypatch):
    secret_payload = "ya29.a0AfH6SMD_SENSITIVE_OAUTH_BEARER_TOKEN_9999"

    def fail_auth():
        raise RuntimeError(f"oauth failure with sensitive payload: {secret_payload}")

    monkeypatch.setattr(google_fit, "_get_credentials", fail_auth)

    result = google_fit.get_morning_summary()

    assert "Google Fit auth" in result
    assert "reconnect Google Workspace" in result
    assert secret_payload not in result


def test_cli_auth_success_prints_fixed_non_sensitive_message(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(google_fit, "authorize_google_fit", lambda: "sensitive-return-value-should-be-ignored")

    google_fit.run_cli(["auth"])

    captured = capsys.readouterr().out
    assert "Google Fit authorization completed." in captured
    assert "sensitive-return-value-should-be-ignored" not in captured
    assert "token.json" not in captured


def test_cli_auth_failure_does_not_leak_raw_exception_or_traceback(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    secret_payload = "ya29.a0AfH6SMD_CLI_LEAK_SECRET_12345"

    def fail_auth():
        raise google_fit.GoogleFitAuthError(f"OAuth failed with {secret_payload}")

    monkeypatch.setattr(google_fit, "authorize_google_fit", fail_auth)

    google_fit.run_cli(["auth"])

    captured = capsys.readouterr().out
    assert "Google Fit authorization failed. Please reconnect Google Workspace." in captured
    assert secret_payload not in captured
    assert "Traceback" not in captured
