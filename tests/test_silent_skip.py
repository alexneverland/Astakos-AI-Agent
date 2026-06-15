"""
Tests για το SILENT_SKIP flow στο job_check_routines() (clients/telegram_bot.py).
Stubs βαριές dependencies ώστε να τρέχει χωρίς production env.
Τρέξε: python tests/test_silent_skip.py   ή   pytest tests/test_silent_skip.py
"""
import os
import sqlite3
import sys
import types
import tempfile
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

# ─────────────────────────────────────────────────────────────
# Stub ΟΛΕΣ τις βαριές dependencies ΠΡΙΝ import του bot
# ─────────────────────────────────────────────────────────────

_TMP_BASE = tempfile.mkdtemp()   # persistent temp dir για το config.BASE_DIR


def _stub_modules():
    # ── config (force-replace) ────────────────────────────────
    cfg = types.ModuleType("config")
    cfg.TELEGRAM_TOKEN                   = "fake_token"
    cfg.TELEGRAM_CHAT_ID                 = "123456"
    cfg.PHOTOS_DIR                       = os.path.join(_TMP_BASE, "photos")
    cfg.PHOTOS_INDEX_FILE                = os.path.join(_TMP_BASE, "photos_index.json")
    cfg.BASE_DIR                         = _TMP_BASE
    cfg.ROUTINES_DB                      = os.path.join(_TMP_BASE, "routines.db")
    cfg.ROUTINE_MISS_GRACE_MINUTES       = 90
    cfg.PROACTIVE_ROUTINE_WINDOW_MINUTES = 30
    sys.modules["config"] = cfg

    # ── langchain_core ────────────────────────────────────────
    for mod in ["langchain_core", "langchain_core.messages"]:
        sys.modules[mod] = types.ModuleType(mod)
    sys.modules["langchain_core.messages"].HumanMessage = MagicMock
    sys.modules["langchain_core.messages"].AIMessage    = MagicMock

    # ── memory.* ──────────────────────────────────────────────
    for mod in [
        "memory", "memory.event_log", "memory.vector_store",
        "memory.working_memory", "memory.session_memory",
        "memory.context_builder", "memory.routine_db",
    ]:
        sys.modules[mod] = types.ModuleType(mod)

    el = sys.modules["memory.event_log"]
    el.log_event                 = MagicMock()
    el.is_duplicate_notification = MagicMock(return_value=False)
    el.is_duplicate_routine      = MagicMock(return_value=False)

    sys.modules["memory.vector_store"].memory = MagicMock()

    wm = sys.modules["memory.working_memory"]
    wm.update_working_memory             = MagicMock()
    wm.update_capabilities_from_exchange = MagicMock()

    sm = sys.modules["memory.session_memory"]
    sm.trigger_memory_sifter  = MagicMock()
    sm.log_exchange           = MagicMock()
    sm._run_session_summary   = MagicMock()
    sm.startup_stale_cleanup  = MagicMock()

    rdb = sys.modules["memory.routine_db"]
    rdb.get_routine_notify_info    = MagicMock(return_value={"cooldown_hours": 4})
    rdb.mark_routine_notified      = MagicMock()
    rdb.save_pending_confirmation  = MagicMock()
    rdb.remove_pending_confirmation = MagicMock()
    rdb.decay_routine              = MagicMock()
    rdb.confirm_routine            = MagicMock()
    rdb.mark_routine_responded     = MagicMock()
    rdb.clear_pending_confirmations = MagicMock()
    rdb.mark_routine_ignored       = MagicMock()
    # νέα stubs για muted_until
    rdb.get_routine_muted_until    = MagicMock(return_value=None)   # δεν είναι muted by default
    rdb.set_routine_muted_until    = MagicMock()
    rdb.clear_routine_muted_until  = MagicMock()

    # ── core.* ────────────────────────────────────────────────
    for mod in [
        "core", "core.brain", "core.graph", "core.agents",
        "core.exceptions", "core.event_bus",
        "core.routine_state", "core.prompts",
    ]:
        sys.modules[mod] = types.ModuleType(mod)

    brain = sys.modules["core.brain"]
    brain.llm             = MagicMock()
    brain.safe_llm_invoke = MagicMock(return_value=MagicMock(content="ok"))

    sys.modules["core.graph"].graph = MagicMock()

    agents = sys.modules["core.agents"]
    agents.clean_message   = MagicMock(side_effect=lambda x: x)
    agents.filter_messages = MagicMock(side_effect=lambda x: x)

    exc = sys.modules["core.exceptions"]
    exc.SchedulerCrashError = type("SchedulerCrashError", (Exception,), {})
    exc.PendingTimeoutError = type("PendingTimeoutError",  (Exception,), {})
    exc.DBWriteError        = type("DBWriteError",         (Exception,), {})

    sys.modules["core.event_bus"].bus = MagicMock()

    rs = sys.modules["core.routine_state"]
    class _RS:
        ACTIVE  = "active"
        LEARNED = "learned"
    rs.RoutineState  = _RS
    rs.is_notifiable = lambda s: s == "active"

    # ── services.* ────────────────────────────────────────────
    for mod in ["services", "services.gemini", "services.embeddings"]:
        sys.modules[mod] = types.ModuleType(mod)
    sys.modules["services.gemini"].safe_gemini_call = MagicMock(return_value="ok")
    sys.modules["services.embeddings"].embeddings   = MagicMock()

    # ── tools.* ───────────────────────────────────────────────
    for mod in ["tools", "tools.telegram"]:
        sys.modules[mod] = types.ModuleType(mod)
    tg = sys.modules["tools.telegram"]
    tg.send_telegram_msg      = MagicMock()
    tg.send_telegram_voice    = MagicMock()
    tg.send_telegram_msg_full = MagicMock()

    # ── python-telegram-bot ───────────────────────────────────
    for mod in ["telegram", "telegram.ext"]:
        sys.modules[mod] = types.ModuleType(mod)


_stub_modules()
import clients.telegram_bot as bot  # noqa: E402


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _make_routines_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE routines (
            id INTEGER PRIMARY KEY, event_name TEXT, confidence REAL,
            time_str TEXT, day_of_week TEXT, state TEXT, last_triggered TEXT,
            muted_until TEXT DEFAULT NULL
        )
    """)
    for r in rows:
        conn.execute(
            "INSERT INTO routines (id,event_name,confidence,"
            "time_str,day_of_week,state,last_triggered) VALUES "
            "(:id,:event_name,:confidence,:time_str,:day_of_week,:state,:last_triggered)", r
        )
    conn.commit()
    conn.close()  # αναγκαίο στο Windows για να μην κλειδωθεί το db στο TemporaryDirectory cleanup


def _run_job(db_rows, craft_return="κανονικό μήνυμα",
             quiet=False, muted=False, duplicate=False):
    """
    Τρέχει job_check_routines() με mocked εξωτερικά.
    Returns: (sent_messages, logged_events, bus_events)
    """
    sent       = []
    logged     = []
    bus_events = []

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "astakos_routines.db")
        _make_routines_db(db_path, db_rows)

        # Ενημερώνω config.BASE_DIR ώστε το job να βρει το σωστό DB
        sys.modules["config"].BASE_DIR = tmp

        mock_bus = MagicMock()
        mock_bus.emit.side_effect = lambda ev, **kw: bus_events.append(ev)

        with (
            patch.object(bot, "is_quiet_hours",        return_value=quiet),
            patch.object(bot, "is_proactive_muted",    return_value=muted),
            patch.object(bot, "is_duplicate_routine",  return_value=duplicate),
            patch.object(bot, "can_send_proactive",    return_value=True),
            patch.object(bot, "should_skip_proactive_for_recent_activity", return_value=False),
            patch.object(bot, "_craft_proactive_msg",  return_value=craft_return),
            patch.object(bot, "send_telegram_msg",     side_effect=lambda m: sent.append(m)),
            patch.object(bot, "log_event",             side_effect=lambda *a, **kw: logged.append((a[0], a[1]))),
            patch.object(bot, "bus",                   mock_bus),
        ):
            bot.job_check_routines()

    return sent, logged, bus_events


def _today_minus(days):
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")


def _due_routine():
    """Ρουτίνα που πρέπει να πυροδοτηθεί σε ~2 λεπτά (μέσα στο 30' window)."""
    now      = datetime.now()
    # Η ρουτίνα είναι στο target_time = now+30min → time_str = (now+28min)
    time_str = (now + timedelta(minutes=30)).strftime("%H:%M")
    return {
        "id": 1, "event_name": "park_walk", "confidence": 0.9,
        "time_str": time_str, "day_of_week": "Everyday", "state": "active",
        "last_triggered": _today_minus(1),
    }


# ─────────────────────────────────────────────────────────────
# Tests: SILENT_SKIP
# ─────────────────────────────────────────────────────────────

def test_silent_skip_sends_no_message():
    """[SILENT_SKIP] → κανένα μήνυμα δεν στέλνεται."""
    sent, _, _ = _run_job([_due_routine()], craft_return="[SILENT_SKIP]")
    assert sent == [], f"Δεν έπρεπε να σταλεί τίποτα, αλλά στάλθηκε: {sent}"


def test_silent_skip_logs_silent_skip():
    """[SILENT_SKIP] → log_event('routines', 'silent_skip')."""
    _, logged, _ = _run_job([_due_routine()], craft_return="[SILENT_SKIP]")
    assert any(cat == "routines" and action == "silent_skip"
               for cat, action in logged), f"Expected silent_skip, got: {logged}"


def test_silent_skip_updates_last_triggered():
    """[SILENT_SKIP] → last_triggered = σήμερα στη DB."""
    row = _due_routine()
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "astakos_routines.db")
        _make_routines_db(db_path, [row])
        sys.modules["config"].BASE_DIR = tmp

        mock_bus = MagicMock()
        with (
            patch.object(bot, "is_quiet_hours",       return_value=False),
            patch.object(bot, "is_proactive_muted",   return_value=False),
            patch.object(bot, "is_duplicate_routine", return_value=False),
            patch.object(bot, "can_send_proactive",   return_value=True),
            patch.object(bot, "should_skip_proactive_for_recent_activity", return_value=False),
            patch.object(bot, "_craft_proactive_msg", return_value="[SILENT_SKIP]"),
            patch.object(bot, "send_telegram_msg",    return_value=None),
            patch.object(bot, "log_event",            return_value=None),
            patch.object(bot, "bus",                  mock_bus),
        ):
            bot.job_check_routines()

        conn      = sqlite3.connect(db_path)
        row_after = conn.execute("SELECT last_triggered FROM routines WHERE id=1").fetchone()
        conn.close()

    today = datetime.now().strftime("%Y-%m-%d")
    assert row_after[0] == today, f"last_triggered πρέπει {today}, είναι {row_after[0]}"


def test_silent_skip_emits_bus_event():
    """[SILENT_SKIP] → bus.emit('routine_skipped_context')."""
    _, _, bus_events = _run_job([_due_routine()], craft_return="[SILENT_SKIP]")
    assert "routine_skipped_context" in bus_events, f"Bus events: {bus_events}"


def test_silent_skip_with_whitespace():
    """'  [SILENT_SKIP]  ' → μετά trim → ίδια συμπεριφορά."""
    sent, logged, _ = _run_job([_due_routine()], craft_return="  [SILENT_SKIP]  ")
    assert sent == []
    assert any(action == "silent_skip" for _, action in logged)


# ─────────────────────────────────────────────────────────────
# Tests: CONTEXT_SKIP (regression)
# ─────────────────────────────────────────────────────────────

def test_context_skip_sends_message_without_tag():
    """[CONTEXT_SKIP] → στέλνεται μήνυμα, χωρίς το tag."""
    sent, _, _ = _run_job(
        [_due_routine()],
        craft_return="[CONTEXT_SKIP] Κανονικά θα πήγαινες στο πάρκο αλλά βρέχει!",
    )
    assert len(sent) == 1, f"Έπρεπε 1 μήνυμα, στάλθηκαν: {sent}"
    assert "[CONTEXT_SKIP]" not in sent[0]
    assert "πάρκο" in sent[0]


def test_context_skip_logs_context_skip():
    """[CONTEXT_SKIP] → log_event('routines', 'context_skip')."""
    _, logged, _ = _run_job(
        [_due_routine()],
        craft_return="[CONTEXT_SKIP] Βρέχει, δεν πάτε πάρκο!",
    )
    assert any(cat == "routines" and action == "context_skip"
               for cat, action in logged), f"Expected context_skip, got: {logged}"


# ─────────────────────────────────────────────────────────────
# Tests: Normal message (regression)
# ─────────────────────────────────────────────────────────────

def test_normal_msg_is_sent():
    """Κανονικό μήνυμα → στέλνεται αυτούσιο."""
    sent, _, _ = _run_job([_due_routine()], craft_return="Μάστορα, πάμε πάρκο;")
    assert sent == ["Μάστορα, πάμε πάρκο;"], f"Got: {sent}"


def test_normal_msg_no_skip_logs():
    """Κανονικό μήνυμα → ΟΧΙ silent_skip ή context_skip στο log."""
    _, logged, _ = _run_job([_due_routine()], craft_return="Μάστορα, πάμε βόλτα!")
    assert not any(action == "silent_skip"  for _, action in logged)
    assert not any(action == "context_skip" for _, action in logged)


# ─────────────────────────────────────────────────────────────
# Standalone runner
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {fn.__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
