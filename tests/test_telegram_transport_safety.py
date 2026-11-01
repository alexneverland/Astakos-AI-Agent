"""Regression coverage for the real Telegram transport test boundary."""

import requests

from tools.telegram import send_telegram_document, send_telegram_msg


def test_pytest_execution_never_posts_to_real_telegram(monkeypatch):
    """A forgotten caller mock must not turn a unit test into a real delivery."""
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "transport safety test")

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("A test attempted a real Telegram HTTP request")

    monkeypatch.setattr(requests, "post", fail_if_called)

    assert send_telegram_msg("test-only message") is None


def test_pytest_execution_never_posts_document_to_real_telegram(monkeypatch, tmp_path):
    """The direct document transport has the same test-only safety boundary."""
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "document transport safety test")
    test_file = tmp_path / "report.txt"
    test_file.write_text("test", encoding="utf-8")

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("A test attempted a real Telegram HTTP request")

    monkeypatch.setattr(requests, "post", fail_if_called)

    assert send_telegram_document(str(test_file)) is None
