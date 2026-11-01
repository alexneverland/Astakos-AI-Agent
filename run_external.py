"""Run the auto-reloading watchdog for the configured external channel."""

from __future__ import annotations

import importlib
from pathlib import Path

from dotenv import load_dotenv

from core.messaging_channel import resolve_external_channel


ROOT_DIR = Path(__file__).resolve().parent


def selected_watchdog_module(channel: str | None = None) -> str:
    """Return the one watchdog module allowed by the channel selection."""
    selected = resolve_external_channel(channel)
    if selected == "matrix":
        return "run_matrix"
    return "run_telegram"


def main() -> int:
    """Load configuration and hand control to exactly one channel watchdog."""
    load_dotenv(ROOT_DIR / ".env")
    module = importlib.import_module(selected_watchdog_module())
    result = module.run()
    return int(result) if result is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
