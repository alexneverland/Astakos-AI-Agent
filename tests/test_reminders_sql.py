# ================================================================
# Tests: SQL-based reminders flow (post JSON→SQL migration)
# Covers: clients.telegram_bot.job_check_reminders(),
#           clients.telegram_bot.handle_location() (location reminders),
#           main.reminder_worker()
# ================================================================
import os
import sqlite3
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Always an old/future date — we avoid race conditions at the minute level
# without needing to mock datetime.now() inside the functions.
PAST_TIME   = "2020-01-01 00:00"
FUTURE_TIME = "2099-01-01 00:00"


def _make_reminders_db(path, rows):
    """Same schema as scripts/migrate_state.py::create_tables()."""
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task TEXT,
            time TEXT,
            status TEXT DEFAULT 'pending',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    for r in rows:
        conn.execute(
            "INSERT INTO reminders (task, time, status) VALUES (?, ?, ?)",
            (r["task"], r["time"], r.get("status", "pending")),
        )
    conn.commit()
    conn.close()


def _row_status(db_path, task):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT status FROM reminders WHERE task=?", (task,))
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


# ────────────────────────────────────────────────────────────────
# clients.telegram_bot.job_check_reminders()
# ────────────────────────────────────────────────────────────────

class TestJobCheckReminders:

    def _run(self, db_rows, paused=False, duplicate=False):
        import clients.telegram_bot as bot
        import config as cfg

        sent = []
        tmp = tempfile.mkdtemp()
        db_path = os.path.join(tmp, "astakos_state.db")
        _make_reminders_db(db_path, db_rows)

        with (
            patch.object(cfg, "STATE_DB", db_path),
            patch.object(bot, "is_reminders_paused", return_value=paused),
            patch.object(bot, "is_duplicate_notification", return_value=duplicate),
            patch.object(bot, "send_telegram_msg", side_effect=lambda m: sent.append(m)),
            patch.object(bot, "log_event"),
        ):
            bot.job_check_reminders()

        return sent, db_path

    def test_due_reminder_fires_and_marked_done(self):
        sent, db_path = self._run([{"task": "Φάρμακο Kid1", "time": PAST_TIME}])
        assert len(sent) == 1
        assert "Φάρμακο Kid1" in sent[0]
        assert _row_status(db_path, "Φάρμακο Kid1") == "done"

    def test_future_reminder_does_not_fire(self):
        sent, db_path = self._run([{"task": "Ραντεβού γιατρού", "time": FUTURE_TIME}])
        assert sent == []
        assert _row_status(db_path, "Ραντεβού γιατρού") == "pending"

    def test_paused_blocks_all_reminders(self):
        sent, db_path = self._run(
            [{"task": "Στείλε email", "time": PAST_TIME}], paused=True
        )
        assert sent == []
        assert _row_status(db_path, "Στείλε email") == "pending"

    def test_location_reminder_excluded_from_time_query(self):
        # loc:-prefixed time must be ignored by the time-based query,
        # regardless of lexicographical string comparison.
        sent, db_path = self._run([{"task": "Πάρε ψωμί", "time": "loc:home"}])
        assert sent == []
        assert _row_status(db_path, "Πάρε ψωμί") == "pending"

    def test_duplicate_notification_skipped_and_left_pending(self):
        # is_duplicate_notification=True → continue, not UPDATE.
        sent, db_path = self._run(
            [{"task": "Πλύσιμο αυτοκινήτου", "time": PAST_TIME}], duplicate=True
        )
        assert sent == []
        assert _row_status(db_path, "Πλύσιμο αυτοκινήτου") == "pending"

    def test_missing_state_db_returns_silently(self):
        import clients.telegram_bot as bot
        import config as cfg

        with tempfile.TemporaryDirectory() as tmp:
            missing_path = os.path.join(tmp, "does_not_exist.db")
            with (
                patch.object(cfg, "STATE_DB", missing_path),
                patch.object(bot, "is_reminders_paused", return_value=False),
                patch.object(bot, "send_telegram_msg") as mocked_send,
            ):
                bot.job_check_reminders()  # should not crash
            mocked_send.assert_not_called()


# ────────────────────────────────────────────────────────────────
# clients.telegram_bot.handle_location() — location reminders block
# ────────────────────────────────────────────────────────────────

class TestLocationReminders:

    HOME = (0.0, 0.0)

    def _run(self, db_rows, lat, lon, radius_m=150):
        import clients.telegram_bot as bot
        import config as cfg

        sent = []
        tmp = tempfile.mkdtemp()
        db_path = os.path.join(tmp, "astakos_state.db")
        gps_path = os.path.join(tmp, "last_location.json")
        _make_reminders_db(db_path, db_rows)

        msg = {"chat": {"id": 1}, "location": {"latitude": lat, "longitude": lon}}

        with (
            patch.object(cfg, "STATE_DB", db_path),
            patch.object(cfg, "GPS_STORAGE_FILE", gps_path),
            patch.object(cfg, "HOME_COORDS", self.HOME),
            patch.object(cfg, "HOME_RADIUS_M", radius_m),
            patch.object(bot, "send_telegram_msg", side_effect=lambda m: sent.append(m)),
        ):
            print("STATE_DB path:", cfg.STATE_DB, "Exists:", os.path.exists(cfg.STATE_DB))
            bot.handle_location(msg, live_update=True)

        return sent, db_path

    def test_location_reminder_fires_within_radius(self):
        # Exactly the same coordinates as HOME_COORDS → distance 0
        sent, db_path = self._run(
            [{"task": "Βγάλε το κουνέλι", "time": "loc:home"}],
            lat=self.HOME[0], lon=self.HOME[1],
        )
        assert len(sent) == 1
        assert "Βγάλε το κουνέλι" in sent[0]
        assert _row_status(db_path, "Βγάλε το κουνέλι") == "done"

    def test_location_reminder_does_not_fire_outside_radius(self):
        # ~1.2km north of home_coords (0.01 degree lat ≈ 1.1km) — outside 150m radius
        sent, db_path = self._run(
            [{"task": "Πάρε γάλα", "time": "loc:home"}],
            lat=self.HOME[0] + 0.01, lon=self.HOME[1],
        )
        assert sent == []
        assert _row_status(db_path, "Πάρε γάλα") == "pending"

    def test_time_based_reminder_not_touched_by_location_check(self):
        sent, db_path = self._run(
            [{"task": "Πλήρωσε λογαριασμό", "time": PAST_TIME}],
            lat=self.HOME[0], lon=self.HOME[1],
        )
        assert sent == []
        assert _row_status(db_path, "Πλήρωσε λογαριασμό") == "pending"

    def test_live_location_departure_triggers_followup(self):
        import clients.telegram_bot as bot
        import config as cfg
        import time

        tmp = tempfile.mkdtemp()
        db_path = os.path.join(tmp, "astakos_state.db")
        gps_path = os.path.join(tmp, "last_location.json")
        _make_reminders_db(db_path, [])

        with (
            patch.object(cfg, "STATE_DB", db_path),
            patch.object(cfg, "GPS_STORAGE_FILE", gps_path),
        ):
            # Step 1: Set anchor
            bot.handle_location(
                {"chat": {"id": 1}, "location": {"latitude": 0.0, "longitude": 0.0}},
                live_update=True,
            )

            # Manually mock time passage (46 mins)
            import json

            with open(gps_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["anchor_timestamp"] -= 46 * 60
            with open(gps_path, "w", encoding="utf-8") as f:
                json.dump(data, f)

            # Step 2: Trigger departure
            created = []
            with patch("memory.pending_followups.create_pending_followup", side_effect=lambda **kw: created.append(kw) or 1):
                # 0.01 degrees ~ 1.1km distance > 300m
                bot.handle_location(
                    {"chat": {"id": 1}, "location": {"latitude": 0.01, "longitude": 0.0}},
                    live_update=True,
                )
                bot.handle_location(
                    {"chat": {"id": 1}, "location": {"latitude": 0.01, "longitude": 0.0}},
                    live_update=True,
                )

            assert len(created) == 1
            assert created[0]["topic"] == "departure"
            assert created[0]["metadata"]["anchor_duration_minutes"] >= 45
            assert created[0]["ttl_hours"] == 1

    def test_live_location_departure_retries_after_pending_create_error(self):
        import json
        import clients.telegram_bot as bot
        import config as cfg

        tmp = tempfile.mkdtemp()
        db_path = os.path.join(tmp, "astakos_state.db")
        gps_path = os.path.join(tmp, "last_location.json")
        _make_reminders_db(db_path, [])

        with (
            patch.object(cfg, "STATE_DB", db_path),
            patch.object(cfg, "GPS_STORAGE_FILE", gps_path),
        ):
            bot.handle_location(
                {"chat": {"id": 1}, "location": {"latitude": 0.0, "longitude": 0.0}},
                live_update=True,
            )

            with open(gps_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            state["anchor_timestamp"] -= 46 * 60
            with open(gps_path, "w", encoding="utf-8") as f:
                json.dump(state, f)

            departure_msg = {
                "chat": {"id": 1},
                "location": {"latitude": 0.01, "longitude": 0.0},
            }

            with patch(
                "memory.pending_followups.create_pending_followup",
                side_effect=RuntimeError("database temporarily locked"),
            ):
                bot.handle_location(departure_msg, live_update=True)

            with open(gps_path, "r", encoding="utf-8") as f:
                retry_state = json.load(f)
            assert retry_state["anchor_lat"] == 0.0

            created = []
            with patch(
                "memory.pending_followups.create_pending_followup",
                side_effect=lambda **kwargs: created.append(kwargs) or 99,
            ):
                bot.handle_location(departure_msg, live_update=True)

        assert len(created) == 1
        assert created[0]["topic"] == "departure"


# ────────────────────────────────────────────────────────────────
# main.reminder_worker()
# ────────────────────────────────────────────────────────────────

class TestMainReminderWorker:

    def _run(self, db_rows, monkeypatch):
        import main as main_mod

        sent = []
        tmp = tempfile.mkdtemp()
        db_path = os.path.join(tmp, "astakos_state.db")
        _make_reminders_db(db_path, db_rows)

        monkeypatch.setattr(main_mod, "STATE_DB", db_path)
        monkeypatch.setattr(main_mod, "send_telegram_msg", lambda m: sent.append(m))

        # Forces the while loop to run EXACTLY once:
        # the first wait() sets the shutdown_event and returns,
        # so the next while-check exits the function without an actual sleep.
        def fake_wait(timeout=None):
            main_mod.shutdown_event.set()
            return True

        main_mod.shutdown_event.clear()
        monkeypatch.setattr(main_mod.shutdown_event, "wait", fake_wait)

        try:
            main_mod.reminder_worker()
        finally:
            main_mod.shutdown_event.clear()

        return sent, db_path

    def test_due_reminder_fires_and_marked_done(self, monkeypatch):
        sent, db_path = self._run(
            [{"task": "Ποτίσματα βάλσαμα", "time": PAST_TIME}], monkeypatch
        )
        assert len(sent) == 1
        assert "Ποτίσματα βάλσαμα" in sent[0]
        assert _row_status(db_path, "Ποτίσματα βάλσαμα") == "done"

    def test_future_reminder_does_not_fire(self, monkeypatch):
        sent, db_path = self._run(
            [{"task": "Service αυτοκινήτου", "time": FUTURE_TIME}], monkeypatch
        )
        assert sent == []
        assert _row_status(db_path, "Service αυτοκινήτου") == "pending"

    def test_location_reminder_excluded(self, monkeypatch):
        sent, db_path = self._run(
            [{"task": "Πάρε ψωμί", "time": "loc:home"}], monkeypatch
        )
        assert sent == []
        assert _row_status(db_path, "Πάρε ψωμί") == "pending"
