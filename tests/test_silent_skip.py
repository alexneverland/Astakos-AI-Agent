"""
Tests for the SILENT_SKIP flow in job_check_routines() (clients/telegram_bot.py).
Stubs heavy dependencies so that it runs without a production env.
Run: python tests/test_silent_skip.py   or   pytest tests/test_silent_skip.py
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
# Stub ALL heavy dependencies BEFORE importing the bot
# ─────────────────────────────────────────────────────────────

_TMP_BASE = tempfile.mkdtemp()   # persistent temp dir for config.BASE_DIR

# All module names that _stub_modules() replaces in sys.modules.
# IMPORTANT (fixed): snapshot + stubbing + "import clients.telegram_bot"
# They are NOT done at the module level (collection time) — they are done inside the
# setup_module() (see below). Reason: pytest performs collection (import)
# OF ALL test files BEFORE the execution of ANY test begins — so if
# stubbing was done at the module level, "poisoning" sys.modules for EVERYTHING
# the other test files (both before AND after alphabetically), even with one
# teardown_module() at the end, since the damage had already been done during the collection phase —
# long before the teardown_module() of this file runs (e.g.
# tests/test_routine_schedule_control.py was getting an AttributeError
# "module 'memory.routine_db' has no attribute 'find_routines_by_name'" because
# exactly that was happening — it was seeing the stub module, not the real one).
# With setup_module()/teardown_module(), the replacement is limited EXACTLY
# in the execution window (not collection) of this file.
_STUB_MODULE_NAMES = [
    "config",
    "langchain_core", "langchain_core.messages",
    "memory", "memory.event_log", "memory.vector_store",
    "memory.working_memory", "memory.session_memory", "memory.pending_followups",
    "memory.context_builder", "memory.routine_db",
    "core", "core.brain", "core.graph", "core.agents",
    "core.exceptions", "core.event_bus",
    "core.routine_state", "core.prompts", "core.utils",
    "services", "services.gemini", "services.embeddings", "services.context_extractor", "services.messenger_intent", "services.routine_context",
    "services.routine_conditions",
    "tools", "tools.telegram",
    "telegram", "telegram.ext",
]
_ORIGINAL_MODULES = {}  # populated inside setup_module(), NOT at collection time
bot = None  # populated inside setup_module() with clients.telegram_bot (stubbed deps)


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
        "memory.working_memory", "memory.session_memory", "memory.pending_followups",
        "memory.context_builder", "memory.routine_db",
        "memory.pending_assets",
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
    sm.run_memory_sifter_fast = MagicMock(return_value=[])
    sm.run_memory_sifter_slow = MagicMock()
    sm.log_exchange           = MagicMock()
    sm._run_session_summary   = MagicMock()
    sm.startup_stale_cleanup  = MagicMock()
    sm._maybe_trigger_auto_session_summary = MagicMock()
    pf = sys.modules["memory.pending_followups"]
    pf.ensure_pending_followups_table = lambda: None
    pf.maybe_create_followup_from_exchange = lambda *a, **k: None
    pf.maybe_resolve_followups_from_user_message = lambda *a, **k: 0
    pf.looks_like_followup_resolution_update = lambda *a, **k: False
    pf.extract_followup_candidate_with_llm = lambda *a, **k: None
    pf.create_pending_followup_from_candidate = lambda *a, **k: None
    pf.get_recently_resolved_followups = lambda *a, **k: []
    pf.candidate_is_distinct_from_recently_resolved = lambda *a, **k: True
    pf.get_due_pending_followups = lambda *a, **k: []
    pf.mark_followup_sent = lambda *a, **k: None
    pf.expire_old_followups = lambda *a, **k: 0
    pf.has_recent_sent_followup = lambda *a, **k: False
    pf.has_recent_sent_followup_for_arc = lambda *a, **k: False
    pf.build_followup_arc_key = lambda topic, subject: f"{topic}::{subject}"
    pf.record_followup_outcome = lambda *a, **k: None
    pa = sys.modules["memory.pending_assets"]
    pa.clear_expired_pending_assets = MagicMock()
    pa.process_pending_assets_from_message = MagicMock()
    pa.get_pending_asset = MagicMock(return_value=None)
    pa.get_latest_pending_asset = MagicMock(return_value=None)
    pa.mark_pending_asset_confirmed = MagicMock()
    pa.mark_pending_asset_rejected = MagicMock()
    pa.mark_pending_asset_cancelled = MagicMock()
    pa.create_pending_asset_archive = MagicMock()
    pa.classify_pending_asset_reply = MagicMock(return_value=None)
    pa.looks_like_asset_confirmation_prompt = MagicMock(return_value=False)
    pa.is_reply_to_recent_asset_prompt = MagicMock(return_value=False)

    rdb = sys.modules["memory.routine_db"]
    import enum
    class MockRoutineState(enum.Enum):
        ACTIVE = "active"
        INACTIVE = "inactive"
        IGNORED = "ignored"
        TRIGGER_PENDING = "trigger_pending"
        CONFIRMED = "confirmed"
    rdb.RoutineState = MockRoutineState
    rdb.get_routine_state = MagicMock(return_value=MockRoutineState.TRIGGER_PENDING)
    rdb.get_routine_notify_info    = MagicMock(return_value={"cooldown_hours": 4})
    rdb.mark_routine_notified      = MagicMock()
    rdb.save_pending_confirmation  = MagicMock()
    rdb.remove_pending_confirmation = MagicMock()
    rdb.decay_routine              = MagicMock()
    rdb.confirm_routine            = MagicMock()
    rdb.mark_routine_responded     = MagicMock()
    rdb.clear_pending_confirmations = MagicMock()
    rdb.mark_routine_ignored       = MagicMock()
    # new stubs for muted_until
    rdb.get_routine_muted_until    = MagicMock(return_value=None)   # not muted by default
    rdb.set_routine_muted_until    = MagicMock()
    rdb.clear_routine_muted_until  = MagicMock()
    # new stubs for seasonal/temporary inactivity (active_from/active_until/paused_until)
    rdb.get_routine_schedule_meta  = MagicMock(return_value={
        "active_from": None, "active_until": None, "paused_until": None,
        "resume_rule": None, "pause_reason": None,
    })  # by default: no routine is inactive
    rdb.is_routine_temporarily_inactive_meta = MagicMock(return_value=(False, None))
    rdb.set_routine_paused_until   = MagicMock()
    rdb.clear_routine_paused_until = MagicMock()
    rdb.set_routine_active_window  = MagicMock()
    rdb.set_routine_resume_rule    = MagicMock()
    rdb.get_routine_condition      = MagicMock(return_value={})
    rdb.get_routine_conditions     = MagicMock(return_value=[])
    rdb.get_context_state          = MagicMock(return_value=None)
    # new stubs for sentimental
    rdb.get_sentimental_info       = MagicMock(return_value={
        "sentimental": 0, "muted_from": None, "muted_until": None,
        "sentimental_send_every": 2, "sentimental_last_sent": None, "sentimental_silenced": False
    })
    rdb.set_routine_sentimental    = MagicMock()
    rdb.update_sentimental_last_sent = MagicMock()
    rdb.set_sentimental_silenced   = MagicMock()

    # ── core.* ────────────────────────────────────────────────
    for mod in [
        "core", "core.brain", "core.graph", "core.agents",
        "core.exceptions", "core.event_bus",
        "core.routine_state", "core.prompts", "core.utils",
    ]:
        sys.modules[mod] = types.ModuleType(mod)

    sys.modules["core.utils"].is_simple_chat_fast_path_candidate = MagicMock(return_value=False)

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

    for mod in [
        "services", "services.gemini", "services.embeddings",
        "services.routine_context", "services.routine_conditions",
        "services.context_extractor", "services.messenger_intent",
    ]:
        sys.modules[mod] = types.ModuleType(mod)

    sys.modules["services.context_extractor"].extract_and_update_context_flags = MagicMock()
    sys.modules["services.messenger_intent"].classify_messenger_intent = MagicMock(return_value=None)

    sys.modules["services.routine_context"].build_runtime_routine_context = MagicMock(return_value={
        "today": "2026-06-17",
        "alexandros_away_from_home": False,
        "football_season": True,
        "school_open": True,
        "current_shift": None,
        "sofia_work_mode": "office"
    })
    sys.modules["services.gemini"].safe_gemini_call = MagicMock(return_value="ok")
    sys.modules["services.embeddings"].embeddings   = MagicMock()
    sys.modules["services.routine_conditions"].evaluate_routine_condition = MagicMock(
        return_value={"allowed": True, "reason": None}
    )
    sys.modules["services.routine_conditions"].evaluate_routine_conditions = MagicMock(
        return_value={"allowed": True, "results": [], "matched_count": 0, "failed_count": 0}
    )

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


def setup_module(module):
    """
    pytest xunit-style hook: runs ONCE, EXACTLY before the FIRST test of this
    file is executed (EXECUTION phase) — NOT during the collection phase.
    Here (and not at the module level) we perform snapshot + stubbing + import, so
    that the "poisoned" sys.modules exists ONLY while the tests of
    this file are running — not during the collection of all test files.
    """
    global bot
    _ORIGINAL_MODULES.update({name: sys.modules.get(name) for name in _STUB_MODULE_NAMES})
    _stub_modules()
    import clients.telegram_bot as _bot_module
    bot = _bot_module


def teardown_module(module):
    """
    pytest xunit-style hook: runs ONCE, after the LAST test of this
    file. Restores sys.modules to the state it was in before
    setup_module(), so that fake stub modules do not leak into other test
    files running in the same pytest process before or after this one.
    It does not affect the tests of THIS file (all run with the stubs, as before,
    just now within the setup_module()/teardown_module() window).
    """
    global bot
    for name in _STUB_MODULE_NAMES:
        original = _ORIGINAL_MODULES.get(name)
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original
    # clients.telegram_bot was loaded in setup_module() using the
    # FAKE dependencies. We remove it so that the next test file that does it
    # import to re-run the real module on the REAL (just
    # restored) dependencies.
    sys.modules.pop("clients.telegram_bot", None)
    bot = None


def _fixed_now():
    return datetime(2026, 6, 17, 12, 0)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _make_routines_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE routines ( priority INTEGER DEFAULT 0, conflict_group TEXT, condition_type TEXT, condition_payload TEXT, condition_mode TEXT,
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
    conn.close()  # necessary on Windows to prevent db locking during TemporaryDirectory cleanup


def _run_job(
    db_rows,
    craft_return="κανονικό μήνυμα",
    quiet=False,
    muted=False,
    duplicate=False,
    muted_until=None,
    sentimental_info=None,
    random_value=0.99,
):
    """
    Runs job_check_routines() with mocked externals.
    Returns: (sent_messages, logged_events, bus_events)
    """
    sent       = []
    logged     = []
    bus_events = []
    rdb = sys.modules["memory.routine_db"]
    for mock_name in (
        "mark_routine_notified",
        "save_pending_confirmation",
        "remove_pending_confirmation",
        "get_routine_muted_until",
        "set_routine_muted_until",
        "get_sentimental_info",
        "set_routine_sentimental",
        "update_sentimental_last_sent",
    ):
        getattr(rdb, mock_name).reset_mock()
    rdb.get_routine_muted_until.return_value = muted_until
    rdb.get_sentimental_info.return_value = sentimental_info or {
        "sentimental": 0, "muted_from": None, "muted_until": None,
        "sentimental_send_every": 2, "sentimental_last_sent": None, "sentimental_silenced": False
    }

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "astakos_routines.db")
        _make_routines_db(db_path, db_rows)

        # Update config.BASE_DIR so that the job can find the correct DB
        sys.modules["config"].BASE_DIR = tmp

        mock_bus = MagicMock()
        mock_bus.emit.side_effect = lambda ev, **kw: bus_events.append(ev)

        with (
            patch.object(bot, "datetime", type("FrozenDateTime", (), {"now": staticmethod(_fixed_now)})),
            patch.object(bot, "is_quiet_hours",        return_value=quiet),
            patch.object(bot, "is_proactive_muted",    return_value=muted),
            patch.object(bot, "is_duplicate_routine",  return_value=duplicate),
            patch.object(bot, "can_send_proactive",    return_value=True),
            patch.object(bot, "should_skip_proactive_for_recent_activity", return_value=False),
            patch.object(bot, "_craft_proactive_msg",  return_value=craft_return),
            patch.object(bot, "send_telegram_msg",     side_effect=lambda m: sent.append(m)),
            patch.object(bot, "log_event",             side_effect=lambda *a, **kw: logged.append((a[0], a[1]))),
            patch.object(bot, "bus",                   mock_bus),
            patch("random.random", return_value=random_value),
        ):
            bot.job_check_routines()

    return sent, logged, bus_events


def _run_missed_job(db_rows, craft_return="Ε, πήγε καλά; 😊", muted_until=None, sentimental_info=None):
    """Runs startup_check_missed_routines() with mocked external dependencies."""
    sent       = []
    logged     = []
    bus_events = []
    rdb = sys.modules["memory.routine_db"]
    for mock_name in (
        "mark_routine_notified",
        "save_pending_confirmation",
        "remove_pending_confirmation",
        "get_routine_muted_until",
        "set_routine_muted_until",
        "get_sentimental_info",
        "set_routine_sentimental",
        "update_sentimental_last_sent",
    ):
        getattr(rdb, mock_name).reset_mock()
    rdb.get_routine_muted_until.return_value = muted_until
    rdb.get_sentimental_info.return_value = sentimental_info or {
        "sentimental": 0, "muted_from": None, "muted_until": None,
        "sentimental_send_every": 2, "sentimental_last_sent": None, "sentimental_silenced": False
    }

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "astakos_routines.db")
        _make_routines_db(db_path, db_rows)
        sys.modules["config"].BASE_DIR = tmp
        sys.modules["config"].ROUTINE_MISS_GRACE_MINUTES = 60

        mock_bus = MagicMock()
        mock_bus.emit.side_effect = lambda ev, **kw: bus_events.append(ev)

        with (
            patch.object(bot, "datetime", type("FrozenDateTime", (), {"now": staticmethod(_fixed_now)})),
            patch.object(bot, "is_quiet_hours",       return_value=False),
            patch.object(bot, "is_proactive_muted",   return_value=False),
            patch.object(bot, "is_duplicate_routine", return_value=False),
            patch.object(bot, "_craft_deferred_msg",  return_value=craft_return),
            patch.object(bot, "_build_proactive_memory_context", return_value="ctx"),
            patch.object(bot, "_infer_muted_until",   return_value="2026-06-26"),
            patch.object(bot, "_infer_sentimental",   return_value=True),
            patch.object(bot, "send_telegram_msg",    side_effect=lambda msg: sent.append(msg)),
            patch.object(bot, "log_event",            side_effect=lambda c, a, **kw: logged.append((c, a))),
            patch.object(bot, "bus",                  mock_bus),
        ):
            bot.startup_check_missed_routines()

    return sent, logged, bus_events


def _today_minus(days):
    # ATTENTION: must be calculated relative to the FROZEN _fixed_now(), not to
    # the actual datetime.now(). The job_check_routines() runs with
    # bot.datetime patched to _fixed_now() (2026-06-17 12:00), so the
    # last_triggered must be "yesterday" IN RELATION TO THIS date.
    # Bug fixed: when the actual "today" was used, as soon as
    # the actual date passed 2026-06-17, the last_triggered
    # (actual "yesterday") COINCIDENTALLY coincided with the frozen today_str
    # ("2026-06-17"), making the routine appear "already triggered today"
    # in the SQL WHERE (last_triggered != today_str) — all due routines
    # were silently filtered, without exception/print, empty sent/logged/bus_events.
    return (_fixed_now() - timedelta(days=days)).strftime("%Y-%m-%d")


def _due_routine():
    """Routine that must be triggered in ~10 minutes (within the 15' window)."""
    now      = _fixed_now()
    # The routine is at target_time = now+10min → within the 15' window
    time_str = (now + timedelta(minutes=10)).strftime("%H:%M")
    return {
        "id": 1, "event_name": "park_walk", "confidence": 0.9,
        "time_str": time_str, "day_of_week": "Everyday", "state": "active",
        "last_triggered": _today_minus(1),
    }


def _missed_routine():
    """Routine that missed the startup check within the grace window."""
    now = _fixed_now()
    time_str = (now - timedelta(minutes=20)).strftime("%H:%M")
    return {
        "id": 1, "event_name": "park_walk", "confidence": 0.9,
        "time_str": time_str, "day_of_week": "Everyday", "state": "active",
        "last_triggered": _today_minus(1),
    }


# ─────────────────────────────────────────────────────────────
# Tests: SILENT_SKIP
# ─────────────────────────────────────────────────────────────

def test_silent_skip_sends_no_message():
    """[SILENT_SKIP] → no message is sent."""
    sent, _, _ = _run_job([_due_routine()], craft_return="[SILENT_SKIP]")
    assert sent == [], f"Δεν έπρεπε να σταλεί τίποτα, αλλά στάλθηκε: {sent}"


def test_silent_skip_logs_silent_skip():
    """[SILENT_SKIP] → log_event('routines', 'routine_silent_skip')."""
    _, logged, _ = _run_job([_due_routine()], craft_return="[SILENT_SKIP]")
    assert any(cat == "routines" and action == "routine_silent_skip"
               for cat, action in logged), f"Expected routine_silent_skip, got: {logged}"


def test_silent_skip_updates_last_triggered():
    """[SILENT_SKIP] → last_triggered = today in the DB."""
    row = _due_routine()
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "astakos_routines.db")
        _make_routines_db(db_path, [row])
        sys.modules["config"].BASE_DIR = tmp

        mock_bus = MagicMock()
        with (
            patch.object(bot, "datetime", type("FrozenDateTime", (), {"now": staticmethod(_fixed_now)})),
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

    today = _fixed_now().strftime("%Y-%m-%d")
    assert row_after[0] == today, f"last_triggered πρέπει {today}, είναι {row_after[0]}"


def test_silent_skip_emits_bus_event():
    """[SILENT_SKIP] → bus.emit('routine_skipped_context')."""
    _, _, bus_events = _run_job([_due_routine()], craft_return="[SILENT_SKIP]")
    assert "routine_skipped_context" in bus_events, f"Bus events: {bus_events}"


def test_silent_skip_with_whitespace():
    """'  [SILENT_SKIP]  ' → after trim → same behavior."""
    sent, logged, _ = _run_job([_due_routine()], craft_return="  [SILENT_SKIP]  ")
    assert sent == []
    assert any(action == "routine_silent_skip" for _, action in logged)


def test_already_muted_routine_does_not_send_sentimental_followup():
    """muted_until active → routine_silent_skip only, without a second emotional/proactive send."""
    rdb = sys.modules["memory.routine_db"]
    sent, logged, _ = _run_job(
        [_due_routine()],
        craft_return="δεν πρέπει να χρησιμοποιηθεί",
        muted_until="2026-06-25",
        sentimental_info={
            "sentimental": True,
            "muted_from": "2026-06-16",
            "muted_until": "2026-06-25",
            "sentimental_send_every": 2,
            "sentimental_last_sent": None,
            "sentimental_silenced": False,
        },
    )

    assert sent == []
    assert any(action == "routine_silent_skip" for _, action in logged)
    rdb.update_sentimental_last_sent.assert_not_called()


# ─────────────────────────────────────────────────────────────
# Tests: CONTEXT_SKIP (regression)
# ─────────────────────────────────────────────────────────────

def test_context_skip_does_not_send_message():
    """[CONTEXT_SKIP] → no message is sent to the user."""
    sent, _, _ = _run_job(
        [_due_routine()],
        craft_return="[CONTEXT_SKIP] Κανονικά θα πήγαινες στο πάρκο αλλά βρέχει!",
    )
    assert sent == [], f"Δεν έπρεπε να σταλεί μήνυμα, στάλθηκαν: {sent}"


def test_context_skip_logs_context_skip():
    """[CONTEXT_SKIP] → log_event('routines', 'routine_context_skip')."""
    _, logged, _ = _run_job(
        [_due_routine()],
        craft_return="[CONTEXT_SKIP] Βρέχει, δεν πάτε πάρκο!",
    )
    assert any(cat == "routines" and action == "routine_context_skip"
               for cat, action in logged), f"Expected routine_context_skip, got: {logged}"


def test_context_skip_does_not_create_pending_confirmation():
    """[CONTEXT_SKIP] → no message, no memory pending, no DB pending save."""
    rdb = sys.modules["memory.routine_db"]
    bot.pending_routine_confirmations.clear()
    sent, _, _ = _run_job(
        [_due_routine()],
        craft_return="[CONTEXT_SKIP] Ο μικρός λείπει, σήμερα μόνο νοσταλγία.",
    )
    assert sent == []
    assert bot.pending_routine_confirmations == {}
    rdb.save_pending_confirmation.assert_not_called()
    rdb.mark_routine_notified.assert_not_called()


def test_context_skip_can_set_muted_window():
    """[CONTEXT_SKIP] with a long-running blocker → writes muted_until immediately."""
    rdb = sys.modules["memory.routine_db"]
    with (
        patch.object(bot, "_build_proactive_memory_context", return_value="camp context"),
        patch.object(bot, "_infer_muted_until", return_value="2026-06-26"),
        patch.object(bot, "_infer_sentimental", return_value=True),
    ):
        _run_job(
            [_due_routine()],
            craft_return="[CONTEXT_SKIP] Περίεργη η ώρα χωρίς τον μικρό σήμερα, ε;",
            sentimental_info={
                "sentimental": None, "muted_from": None, "muted_until": None,
                "sentimental_send_every": 2, "sentimental_last_sent": None, "sentimental_silenced": False,
            },
        )
    rdb.set_routine_muted_until.assert_called_once_with(1, "2026-06-26")
    rdb.set_routine_sentimental.assert_called_once_with(1, True)


def test_shift_mode_block_does_not_trigger_sentimental_override():
    """Work/shift blocks should stay blocked, even if the random sentimental gate fires."""
    rdb = sys.modules["memory.routine_db"]
    rdb.get_routine_conditions.return_value = [
        {
            "condition_type": "shift_mode",
            "condition_payload": '{"flag": "current_shift", "equals": "afternoon"}',
            "condition_mode": "suppress_when_true",
        }
    ]
    sys.modules["services.routine_conditions"].evaluate_routine_conditions.return_value = {
        "allowed": False,
        "results": [{"allowed": False, "reason": "shift_mode_suppressed"}],
        "matched_count": 0,
        "failed_count": 1,
    }

    try:
        sent, logged, _ = _run_job(
            [dict(_due_routine(), event_name="Πάρκο με τον Αλέξανδρο")],
            random_value=0.0,
        )
    finally:
        rdb.get_routine_conditions.return_value = []
        sys.modules["services.routine_conditions"].evaluate_routine_conditions.return_value = {
            "allowed": True,
            "results": [],
            "matched_count": 0,
            "failed_count": 0,
        }

    assert sent == []
    assert any(action == "routine_condition_blocked" for _, action in logged)
    assert not any(action == "routine_triggered" for _, action in logged)


def test_should_log_routine_skip_respects_ttl(monkeypatch):
    bot._recent_routine_skip_events.clear()

    fake_now = {"value": 1000.0}
    monkeypatch.setattr(bot.time, "time", lambda: fake_now["value"])

    assert bot._should_log_routine_skip(11, "routine_condition_blocked", "x", ttl_seconds=10) is True
    assert bot._should_log_routine_skip(11, "routine_condition_blocked", "x", ttl_seconds=10) is False

    fake_now["value"] = 1011.0
    assert bot._should_log_routine_skip(11, "routine_condition_blocked", "x", ttl_seconds=10) is True


def test_deferred_context_skip_does_not_create_pending_confirmation():
    """Deferred [CONTEXT_SKIP] → neither message nor pending."""
    rdb = sys.modules["memory.routine_db"]
    bot.pending_routine_confirmations.clear()
    sent, logged, bus_events = _run_missed_job(
        [_missed_routine()],
        craft_return="[CONTEXT_SKIP] Περίεργη η ώρα χωρίς τον μικρό σήμερα, ε;",
    )
    assert sent == []
    assert bot.pending_routine_confirmations == {}
    assert any(action == "routine_context_skip" for _, action in logged)
    assert "routine_skipped_context" in bus_events
    rdb.save_pending_confirmation.assert_not_called()
    rdb.mark_routine_notified.assert_not_called()
    rdb.set_routine_muted_until.assert_called_once_with(1, "2026-06-26")


# ─────────────────────────────────────────────────────────────
# Tests: Normal message (regression)
# ─────────────────────────────────────────────────────────────

def test_force_silent_skip_from_state_when_park_already_in_progress():
    snap = {
        "state:alexandros:outing": {"value": "in_progress", "expires_at": None}
    }
    assert bot._force_proactive_skip_from_state("Πάρκο με Αλέξανδρο", snap).startswith("[SILENT_SKIP]")

def test_force_silent_skip_from_state_when_football_off_season():
    snap = {
        "football_season": {"value": "false", "expires_at": "2026-09-01"},
        "state:alexandros:sports_training": {"value": "off_season", "expires_at": "2026-09-01"},
    }
    assert bot._force_proactive_skip_from_state("ποδόσφαιρο Αλέξανδρου", snap).startswith("[SILENT_SKIP]")

def test_force_context_skip_from_state_when_child_away_from_home():
    snap = {
        "alexandros_away_from_home": {"value": "true", "expires_at": "2026-06-25"},
        "alexandros_away_reason": {"value": "camp", "expires_at": "2026-06-25"},
    }
    assert bot._force_proactive_skip_from_state("Πάρκο με Αλέξανδρο", snap).startswith("[CONTEXT_SKIP]")

def test_force_context_skip_from_state_when_child_is_out_with_sofia_for_sleep():
    snap = {
        "alexandros_with_sofia": {"value": "true", "expires_at": "2026-07-05"},
        "alexandros_away_from_home": {"value": "true", "expires_at": "2026-07-05"},
    }
    assert bot._force_proactive_skip_from_state("Ύπνος Αλέξανδρου", snap).startswith("[CONTEXT_SKIP]")

def test_force_proactive_skip_from_state_does_not_skip_park_when_only_out_of_home():
    snap = {
        "user_out_of_home": {"value": "true", "expires_at": None},
        "state:alexandros:outing": {"value": "", "expires_at": None},
        "alexandros_away_from_home": {"value": "false", "expires_at": None},
        "user_at_work": {"value": "false", "expires_at": None},
    }
    assert bot._force_proactive_skip_from_state("Πάρκο με Αλέξανδρο", snap) is None

def test_force_proactive_skip_from_state_returns_silent_skip_for_done_park():
    snap = {
        "state:alexandros:outing": {"value": "done", "expires_at": None}
    }
    assert bot._force_proactive_skip_from_state("Πάρκο με Αλέξανδρο", snap).startswith("[SILENT_SKIP]")

def test_force_proactive_skip_from_context_uses_generic_overlap_and_progress_markers():
    ctx = "Μόλις φτάσαμε στο πάρκο και είμαστε ήδη εκεί με τον μικρό."
    assert bot._force_proactive_skip_from_context("Πάρκο με Αλέξανδρο", ctx) == "[SILENT_SKIP]"


def test_force_proactive_skip_from_context_does_not_skip_without_progress_signal():
    ctx = "Σκεφτόμαστε αργότερα για πάρκο με τον μικρό αν προλάβουμε."
    assert bot._force_proactive_skip_from_context("Πάρκο με Αλέξανδρο", ctx) is None

def test_normal_msg_is_sent():
    """Regular message → sent as is."""
    sent, _, _ = _run_job([_due_routine()], craft_return="Μάστορα, πάμε πάρκο;")
    assert sent == ["Μάστορα, πάμε πάρκο;"], f"Got: {sent}"


def test_normal_msg_no_skip_logs():
    """Normal message → NO routine_silent_skip or routine_context_skip in the log."""
    _, logged, _ = _run_job([_due_routine()], craft_return="Μάστορα, πάμε βόλτα!")
    assert not any(action == "routine_silent_skip"  for _, action in logged)
    assert not any(action == "routine_context_skip" for _, action in logged)

def test_timeout_decay_ignores_stale_pending():
    """
    When a routine has been confirmed (i.e., not TRIGGER_PENDING),
    the timeout decay should not write timeout_decay,
    but pending_stale_cleared instead.
    """
    past_time = _fixed_now() - timedelta(minutes=40)
    bot.pending_routine_confirmations[888] = {"event": "Stale Routine", "sent_at": past_time}

    rdb = sys.modules["memory.routine_db"]
    # Mock state to return ACTIVE
    rdb.get_routine_state.return_value = rdb.RoutineState.ACTIVE

    sent, logged, _ = _run_job([])

    action_types = [a for _, a in logged]



    assert "routine_pending_stale_cleared" in action_types
    assert "routine_timeout_decay" not in action_types

    assert 888 not in bot.pending_routine_confirmations
    assert sent == []

    rdb.mark_routine_ignored.assert_not_called()
    rdb.remove_pending_confirmation.assert_called_once_with(888)

    # Reset mock
    rdb.get_routine_state.return_value = rdb.RoutineState.TRIGGER_PENDING

def test_telegram_bot_contextual_dismiss_skips_decay_for_sofia():
    bot.pending_routine_confirmations = {
        999: {"event": "Στείλε μήνυμα στη Partner (messenger)", "sent_at": _fixed_now()}
    }
    
    rdb = sys.modules["memory.routine_db"]
    rdb.decay_routine.reset_mock()
    rdb.remove_pending_confirmation.reset_mock()
    
    el = sys.modules["memory.event_log"]
    el.log_event.reset_mock()

    bot.handle_message("ήρθαμε θάλασσα, είμαστε μαζί", "123456")

    rdb.decay_routine.assert_not_called()
    rdb.remove_pending_confirmation.assert_called_once_with(999)

    el.log_event.assert_any_call(
        "routines",
        "routine_context_skip",
        routine_id=999,
        event="Στείλε μήνυμα στη Partner (messenger)",
        reason="user_already_with_sofia",
        debug_type="manual_control",
        debug_source="user_message",
        debug_effect="no_decay"
    )


def test_contextual_not_needed_reply_detects_sofia_presence_phrase():
    assert bot._looks_like_contextual_not_needed_reply(
        "Καλά βρε όλοι μαζι δεν ήρθαμε θάλασσα δίπλα μου είναι η Partner"
    ) is True

# ─────────────────────────────────────────────────────────────
# Standalone runner
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import traceback
    setup_module(None)
    try:
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
    finally:
        teardown_module(None)
def test_park_routine_not_skipped_just_because_alexandros_is_with_user():
    import clients.telegram_bot as bot
    snap = {
        "alexandros_away_from_home": {"value": "false"},
        "alexandros_with_user": {"value": "true"},
        "alexandros_with_sofia": {"value": "false"},
        "user_at_work": {"value": "false"},
        "state:alexandros:outing": {"value": ""},
    }
    assert bot._force_proactive_skip_from_state("Πάρκο με Αλέξανδρο", snap) is None

def test_park_routine_skips_when_alexandros_is_with_sofia_without_user():
    import clients.telegram_bot as bot
    snap = {
        "alexandros_away_from_home": {"value": "false"},
        "alexandros_with_user": {"value": "false"},
        "alexandros_with_sofia": {"value": "true"},
        "user_at_work": {"value": "false"},
        "state:alexandros:outing": {"value": ""},
    }
    result = bot._force_proactive_skip_from_state("Πάρκο με Αλέξανδρο", snap)
    assert result is not None
    assert result.startswith("[CONTEXT_SKIP]")
    assert "Partner" in result or "σοφία" in result

def test_force_context_skip_from_state_sleep_does_not_skip_when_all_at_home():
    snap = {
        "alexandros_with_user": {"value": "true", "expires_at": "2026-07-05"},
        "alexandros_with_sofia": {"value": "true", "expires_at": "2026-07-05"},
        "user_out_of_home": {"value": "false", "expires_at": "2026-07-05"},
        "alexandros_away_from_home": {"value": "false", "expires_at": "2026-07-05"},
    }
    assert bot._force_proactive_skip_from_state("Ύπνος Αλέξανδρου", snap) is None

def test_force_context_skip_from_state_sleep_skips_when_user_out_of_home():
    snap = {
        "user_out_of_home": {"value": "true", "expires_at": "2026-07-05"},
    }
    assert bot._force_proactive_skip_from_state("Ύπνος Αλέξανδρου", snap).startswith("[CONTEXT_SKIP] ο User λείπει")

def test_force_context_skip_from_state_sleep_skips_when_user_at_work():
    snap = {
        "user_at_work": {"value": "true", "expires_at": "2026-07-05"},
    }
    assert bot._force_proactive_skip_from_state("Ύπνος Αλέξανδρου", snap).startswith("[CONTEXT_SKIP] ο User λείπει")

def test_force_context_skip_from_state_message_to_sofia_skips_when_together():
    snap = {
        "sofia_with_user": {"value": "true", "expires_at": "2026-07-05"},
    }
    assert bot._force_proactive_skip_from_state("Σύνταξη πρωινού μηνύματος στη Partner στο Messenger", snap).startswith("[CONTEXT_SKIP]")

def test_force_context_skip_from_state_message_to_sofia_does_not_skip_when_apart():
    snap = {
        "sofia_with_user": {"value": "false", "expires_at": "2026-07-05"},
    }
    assert bot._force_proactive_skip_from_state("Σύνταξη πρωινού μηνύματος στη Partner στο Messenger", snap) is None

def test_force_context_skip_from_state_wake_up_skips_when_at_work():
    snap = {
        "user_at_work": {"value": "true", "expires_at": "2026-07-05"},
    }
    assert bot._force_proactive_skip_from_state("ξύπνημα Λάζαρου", snap).startswith("[CONTEXT_SKIP] ο User είναι ήδη στη δουλειά (βάρδια)")

def test_force_context_skip_from_state_wake_up_skips_when_out_of_home():
    snap = {
        "user_out_of_home": {"value": "true", "expires_at": "2026-07-05"},
    }
    assert bot._force_proactive_skip_from_state("ξύπνημα Λάζαρου", snap).startswith("[CONTEXT_SKIP] ο User είναι ήδη εκτός σπιτιού")

def test_force_context_skip_from_state_work_departure_skips_when_at_work():
    snap = {
        "user_at_work": {"value": "true", "expires_at": "2026-07-05"},
    }
    assert bot._force_proactive_skip_from_state("αναχώρηση για δουλειά", snap).startswith("[CONTEXT_SKIP] ο User βρίσκεται ήδη στη δουλειά (βάρδια)")
