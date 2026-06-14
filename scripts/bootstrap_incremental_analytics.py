"""
Bootstrap the incremental analytics SQLite state from shared conversation history.

Default mode is dry-run. Use --apply only after reviewing the dry-run output.
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.analytics_engine import run_analytics_incremental


def _force_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    _force_utf8_console()
    parser = argparse.ArgumentParser(description="Bootstrap incremental analytics state.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write analytics_state.db and promote eligible routines through upsert_routine.",
    )
    parser.add_argument(
        "--state-db",
        default=None,
        help="Optional alternate analytics state DB path for testing.",
    )
    args = parser.parse_args()

    stats = run_analytics_incremental(
        bootstrap=True,
        dry_run=not args.apply,
        state_db_path=args.state_db,
    )
    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"\n[{mode}] Incremental analytics bootstrap stats:")
    for key, value in stats.items():
        if key == "batch_durations":
            print("batch_durations:")
            for batch in value:
                print(f"  - batch {batch['batch']}: {batch['messages']} msgs, {batch['duration']}s")
        else:
            print(f"{key}: {value}")

    if not args.apply:
        print("\nΔεν γράφτηκε τίποτα. Τρέξε ξανά με --apply για να δημιουργηθεί η βάση.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
