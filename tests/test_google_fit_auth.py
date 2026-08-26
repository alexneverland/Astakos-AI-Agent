import json
from unittest.mock import MagicMock

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


def test_cli_steps_success_and_failure_prints_fixed_safe_messages(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Success path
    monkeypatch.setattr(google_fit, "get_steps", lambda days_ago: 99999)
    google_fit.run_cli(["steps", "1"])
    out = capsys.readouterr().out
    assert "Google Fit steps summary retrieved." in out
    assert "99999" not in out

    # Failure path
    monkeypatch.setattr(google_fit, "get_steps", MagicMock(side_effect=RuntimeError("STEPS_ERR_SECRET")))
    google_fit.run_cli(["steps", "1"])
    out_err = capsys.readouterr().out
    assert "Google Fit steps summary unavailable." in out_err
    assert "STEPS_ERR_SECRET" not in out_err


def test_cli_sleep_success_and_failure_prints_fixed_safe_messages(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Success path
    monkeypatch.setattr(google_fit, "get_sleep", lambda days_ago: {"deep_minutes": 120})
    google_fit.run_cli(["sleep", "1"])
    out = capsys.readouterr().out
    assert "Google Fit sleep summary retrieved." in out
    assert "120" not in out
    assert "deep_minutes" not in out

    # Failure path
    monkeypatch.setattr(google_fit, "get_sleep", MagicMock(side_effect=RuntimeError("SLEEP_ERR_SECRET")))
    google_fit.run_cli(["sleep", "1"])
    out_err = capsys.readouterr().out
    assert "Google Fit sleep summary unavailable." in out_err
    assert "SLEEP_ERR_SECRET" not in out_err


def test_cli_heart_success_and_failure_prints_fixed_safe_messages(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Success path
    monkeypatch.setattr(google_fit, "get_heart_rate", lambda days_ago: {"avg_bpm": 72, "max_bpm": 130})
    google_fit.run_cli(["heart", "1"])
    out = capsys.readouterr().out
    assert "Google Fit heart-rate summary retrieved." in out
    assert "72" not in out
    assert "130" not in out

    # Failure path
    monkeypatch.setattr(google_fit, "get_heart_rate", MagicMock(side_effect=RuntimeError("HEART_ERR_SECRET")))
    google_fit.run_cli(["heart", "1"])
    out_err = capsys.readouterr().out
    assert "Google Fit heart-rate summary unavailable." in out_err
    assert "HEART_ERR_SECRET" not in out_err


def test_cli_summary_success_and_failure_prints_fixed_safe_messages(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # 1. Success path (auth succeeds, queries succeed)
    monkeypatch.setattr(google_fit, "_fit_auth_summary", lambda title: None)
    monkeypatch.setattr(google_fit, "get_steps", lambda days_ago: 8000)
    monkeypatch.setattr(google_fit, "get_sleep", lambda days_ago: {"total_minutes": 420, "deep_minutes": 60, "rem_minutes": 60})
    monkeypatch.setattr(google_fit, "get_heart_rate", lambda days_ago: {"avg_bpm": 65, "max_bpm": 110})

    google_fit.run_cli(["summary", "1"])
    out = capsys.readouterr().out
    assert "Google Fit daily summary retrieved." in out
    assert "8000" not in out
    assert "65" not in out

    # 2. Failure path when _fit_auth_summary returns an auth problem string
    auth_warning_text = "⚠️ Google Fit auth: authorization is unavailable"
    monkeypatch.setattr(google_fit, "_fit_auth_summary", lambda title: auth_warning_text)

    # Note that get_daily_summary still returns the auth warning text for Telegram/UI
    assert auth_warning_text in google_fit.get_daily_summary()

    # But run_cli truthfully prints unavailable without leaking any text
    google_fit.run_cli([])
    out_err = capsys.readouterr().out
    assert "Google Fit daily summary unavailable." in out_err
    assert auth_warning_text not in out_err

    # 3. Failure path when an unexpected exception is raised
    monkeypatch.setattr(google_fit, "_generate_daily_summary", MagicMock(side_effect=RuntimeError("SUMMARY_ERR_SECRET")))
    google_fit.run_cli([])
    out_err2 = capsys.readouterr().out
    assert "Google Fit daily summary unavailable." in out_err2
    assert "SUMMARY_ERR_SECRET" not in out_err2
