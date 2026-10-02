"""Standalone selective daily backup entrypoint for the approved 00:00 task."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.daily_backup_job import main


if __name__ == "__main__":
    raise SystemExit(main())
