"""Offline contracts for channel-neutral session finalization."""

from __future__ import annotations

import pytest


def test_finalize_session_archives_before_clearing_working_memory(tmp_path) -> None:
    from services.session_end import finalize_session

    working_memory = tmp_path / "working_memory.txt"
    working_memory.write_text("active context", encoding="utf-8")
    observed: list[tuple[str, str]] = []

    def summarize(*, channel: str) -> None:
        observed.append((channel, working_memory.read_text(encoding="utf-8")))

    finalize_session(
        channel="matrix",
        summary_runner=summarize,
        working_memory_file=working_memory,
        reset_text="EMPTY",
    )

    assert observed == [("matrix", "active context")]
    assert working_memory.read_text(encoding="utf-8") == "EMPTY"


def test_finalize_session_preserves_working_memory_when_archive_fails(tmp_path) -> None:
    from services.session_end import finalize_session

    working_memory = tmp_path / "working_memory.txt"
    working_memory.write_text("keep this", encoding="utf-8")

    def fail_summary(*, channel: str) -> None:
        raise RuntimeError(f"summary failed for {channel}")

    with pytest.raises(RuntimeError, match="summary failed for matrix"):
        finalize_session(
            channel="matrix",
            summary_runner=fail_summary,
            working_memory_file=working_memory,
            reset_text="EMPTY",
        )

    assert working_memory.read_text(encoding="utf-8") == "keep this"


def test_finalize_session_preserves_working_memory_when_archive_reports_failure(tmp_path) -> None:
    from services.session_end import finalize_session

    working_memory = tmp_path / "working_memory.txt"
    working_memory.write_text("keep this", encoding="utf-8")

    with pytest.raises(RuntimeError, match="archive failed"):
        finalize_session(
            channel="telegram",
            summary_runner=lambda *, channel: False,
            working_memory_file=working_memory,
            reset_text="EMPTY",
        )

    assert working_memory.read_text(encoding="utf-8") == "keep this"
