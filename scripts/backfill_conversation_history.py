from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config import BASE_DIR, CONVERSATION_DB_FILE, TELEGRAM_HISTORY_FILE
from memory.conversation_history import LEGACY_FALLBACK_DATE, backfill_legacy_history


WEB_HISTORY_FILE = os.path.join(BASE_DIR, "astakos_chat_history.json")


def _load_json_history(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def main() -> int:
    jobs = [
        ("web", "legacy_web_json", WEB_HISTORY_FILE),
        ("telegram", "legacy_telegram_json", TELEGRAM_HISTORY_FILE),
    ]
    summary = {
        "db_path": CONVERSATION_DB_FILE,
        "fallback_date_for_missing_legacy_dates": LEGACY_FALLBACK_DATE,
        "jobs": {},
    }

    for channel, source, path in jobs:
        history = _load_json_history(path)
        summary["jobs"][source] = {
            "path": path,
            **backfill_legacy_history(
                history,
                channel=channel,
                source=source,
                db_path=CONVERSATION_DB_FILE,
            ),
        }

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
