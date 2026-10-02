"""Local subprocess fixtures: recovery output remains visible and privately logged."""

import sys


def test_recovery_output_reaches_console_and_logs(tmp_path, capsys):
    """Run a real disposable child, not a mocked startup-message intermediate."""
    from services.matrix_backup_maintenance import start_logged_matrix_process, drain_matrix_output
    child = start_logged_matrix_process(
        [sys.executable, "-c", "import sys; print('visible startup'); print('visible error', file=sys.stderr)"],
        log_dir=tmp_path / "runtime",
    )
    assert child.wait(timeout=10) == 0
    drain_matrix_output(child)
    captured = capsys.readouterr()
    assert "visible startup" in captured.out
    assert "visible error" in captured.err
    assert "visible startup" in (tmp_path / "runtime/nightly-matrix.out.log").read_text()
    assert "visible error" in (tmp_path / "runtime/nightly-matrix.err.log").read_text()
