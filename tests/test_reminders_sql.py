# ================================================================
# Tests: SQL-based reminders flow (post JSON→SQL migration)
# Καλύπτει: clients.telegram_bot.job_check_reminders(),
#           clients.telegram_bot.handle_location() (location reminders),
#           main.reminder_worker()
# ================================================================
import os
import sqlite3
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Πάντα παλιά/μελλοντική ημερομηνία — αποφεύγουμε race conditions στο λεπτό
# χωρίς να χρειάζεται να mockάρουμε το datetime.now() μέσα στις συναρτήσεις.
PAST_TIME   = "2020-01-01 00:00"
FUTURE_TIME = "2099-01-01 00:00"


def _make_reminders_db(path, rows):
    """Ίδιο schema με scripts/migrate_state.py::create_tables()."""
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
        sent, db_path = self._run([{"task": "Φάρμακο Αλέξανδρος", "time": PAST_TIME}])
        assert len(sent) == 1
        assert "Φάρμακο Αλέξανδρος" in sent[0]
        assert _row_status(db_path, "Φάρμακο Αλέξανδρος") == "done"

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
        # loc:-prefixed time πρέπει να αγνοείται από το time-based query,
        # ανεξάρτητα από lexicographic σύγκριση strings.
        sent, db_path = self._run([{"task": "Πάρε ψωμί", "time": "loc:home"}])
        assert sent == []
        assert _row_status(db_path, "Πάρε ψωμί") == "pending"

    def test_duplicate_notification_skipped_and_left_pending(self):
        # is_duplicate_notification=True → continue, όχι UPDATE.
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
                bot.job_check_reminders()  # δεν πρέπει να σκάσει
            mocked_send.assert_not_called()


# ────────────────────────────────────────────────────────────────
# clients.telegram_bot.handle_location() — location reminders block
# ────────────────────────────────────────────────────────────────

class TestLocationReminders:

    HOME = (40.646558, 22.939036)

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
            bot.handle_location(msg, live_update=True)

        return sent, db_path

    def test_location_reminder_fires_within_radius(self):
        # Ίδιες ακριβώς συντεταγμένες με HOME_COORDS → distance 0
        sent, db_path = self._run(
            [{"task": "Βγάλε το κουνέλι", "time": "loc:home"}],
            lat=self.HOME[0], lon=self.HOME[1],
        )
        assert len(sent) == 1
        assert "Βγάλε το κουνέλι" in sent[0]
        assert _row_status(db_path, "Βγάλε το κουνέλι") == "done"

    def test_location_reminder_does_not_fire_outside_radius(self):
        # ~1.2km βόρεια του home_coords (0.01 μοίρα lat ≈ 1.1km) — εκτός 150m radius
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

        # Αναγκάζει το while loop να τρέξει ΑΚΡΙΒΩΣ μία φορά:
        # το πρώτο wait() κάνει set() στο shutdown_event και επιστρέφει,
        # οπότε το επόμενο while-check βγάζει τη συνάρτηση χωρίς πραγματικό sleep.
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
