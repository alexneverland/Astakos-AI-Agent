"""Regression tests for the Telegram watchdog shutdown budget."""

import ast
from pathlib import Path


def test_watchdog_timeout_allows_poll_and_cleanup_budget():
    """The watchdog must outlast one poll plus the bounded shutdown work."""
    source = Path("run_telegram.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    timeout = next(
        node.value.value
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "SHUTDOWN_TIMEOUT_SECONDS"
            for target in node.targets
        )
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, int)
    )

    # One 35s poll, two bounded 20s notifications, a 30s drain, and summary work.
    assert timeout >= 140
