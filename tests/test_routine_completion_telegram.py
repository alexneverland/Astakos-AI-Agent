"""
Integration tests for routine completion via the actual Telegram
``handle_message`` path.

Uses the proven ``setup_module`` / ``teardown_module`` stubbing pattern
from ``test_silent_skip.py`` to safely import ``clients.telegram_bot``
without production dependencies.

Asserts:
- a) Pre-emptive selected routine ⇒ only ``mark_routine_triggered_today(id)``
- b) Multiple pending + bare yes ⇒ clarification sender call, no confirm/decay
- c) One pending + yes ⇒ only that ID confirmed/removed
- d) Partner/messenger contextual skip ⇒ return guard; ``decide_completion``
     is never called.
"""
import os
import sys
import types
import tempfile
import sqlite3
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
from memory.conversation_history import (
    append_message as real_append_message,
    load_messages as real_load_messages,
    load_recent_context as real_load_recent_context,
)
from memory.routine_feedback import RoutineFeedbackStore


# ─────────────────────────────────────────────────────────────
# Stub ALL heavy dependencies BEFORE importing the bot
# ─────────────────────────────────────────────────────────────

_TMP_BASE = tempfile.mkdtemp()

_STUB_MODULE_NAMES = [
    "config",
    "langchain_core", "langchain_core.messages",
    "memory", "memory.event_log", "memory.execution_trace", "memory.vector_store",
    "memory.working_memory", "memory.session_memory", "memory.pending_followups",
    "memory.context_builder", "memory.routine_db",
    "memory.pending_assets",
    "core.brain", "core.graph", "core.agents",
    "core.capability_draft",
    "core.exceptions", "core.event_bus",
    "core.routine_state", "core.prompts", "core.utils", "core.i18n", "core.nl_config",
    "services.gemini", "services.embeddings", "services.context_extractor",
    "services.messenger_intent",
    "services.routine_context", "services.routine_conditions",
    "services.routine_context_clarification",
    "services.routine_context_clarification_scheduler",
    "tools", "tools.telegram", "tools.system",
    "telegram", "telegram.ext",
]
_ORIGINAL_MODULES = {}
bot = None


def _stub_modules():
    # ── config ────────────────────────────────────────────────
    cfg = types.ModuleType("config")
    cfg.TELEGRAM_TOKEN            = "fake_token"
    cfg.TELEGRAM_CHAT_ID          = "123456"
    cfg.PHOTOS_DIR                = os.path.join(_TMP_BASE, "photos")
    cfg.PHOTOS_INDEX_FILE         = os.path.join(_TMP_BASE, "photos_index.json")
    cfg.BASE_DIR                  = _TMP_BASE
    cfg.ROUTINES_DB               = os.path.join(_TMP_BASE, "routines.db")
    cfg.ROUTINE_MISS_GRACE_MINUTES       = 90
    cfg.PROACTIVE_ROUTINE_WINDOW_MINUTES = 30
    cfg.NLP_CONFIG         = {}
    cfg.RESPONSE_LANGUAGE  = "Greek"
    cfg.OWNER_NAME         = "User"
    cfg.PARTNER_NAME       = "Partner"
    cfg.KID1_NAME          = "Kid1"
    cfg.KID2_NAME          = "Kid2"
    cfg.BOT_NAME           = "Astakos"
    sys.modules["config"] = cfg

    # ── langchain_core ────────────────────────────────────────
    for mod in ["langchain_core", "langchain_core.messages"]:
        sys.modules[mod] = types.ModuleType(mod)
    sys.modules["langchain_core.messages"].HumanMessage = MagicMock
    sys.modules["langchain_core.messages"].AIMessage    = MagicMock
    sys.modules["langchain_core.messages"].SystemMessage = MagicMock
    sys.modules["langchain_core.messages"].BaseMessage = MagicMock

    # ── memory.* ──────────────────────────────────────────────
    for mod in [
        "memory", "memory.event_log", "memory.execution_trace", "memory.vector_store",
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

    sys.modules["memory.execution_trace"].ExecutionTrace = MagicMock()

    pf = sys.modules["memory.pending_followups"]
    pf.ensure_pending_followups_table = lambda: None
    pf.find_pending_followups = lambda *a, **k: []
    pf.process_followup_exchange = lambda *a, **k: None
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
    pa.get_latest_pending_asset_any = MagicMock(return_value=None)
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
    rdb.RoutineState                      = MockRoutineState
    rdb.get_routine_state                 = MagicMock(return_value=MockRoutineState.TRIGGER_PENDING)
    rdb.get_routine_notify_info           = MagicMock(return_value={"cooldown_hours": 4})
    rdb.mark_routine_notified             = MagicMock()
    rdb.save_pending_confirmation         = MagicMock()
    rdb.remove_pending_confirmation       = MagicMock()
    rdb.decay_routine                     = MagicMock()
    rdb.confirm_routine                   = MagicMock()
    rdb.mark_routine_responded            = MagicMock()
    rdb.clear_pending_confirmations       = MagicMock()
    rdb.mark_routine_ignored              = MagicMock()
    rdb.mark_routine_acknowledged          = MagicMock()
    rdb.acknowledge_pending_draft_offer    = MagicMock(return_value=True)
    rdb.record_routine_skip_today          = MagicMock(return_value={
        "skip_streak": 1,
        "cooldown_applied": False,
        "cooldown_hours": None,
    })
    rdb.pause_routine_indefinitely         = MagicMock()
    rdb.get_active_routine_catalog         = MagicMock(return_value=[])
    rdb.get_routine_muted_until           = MagicMock(return_value=None)
    rdb.set_routine_muted_until           = MagicMock()
    rdb.clear_routine_muted_until         = MagicMock()
    rdb.get_routine_schedule_meta         = MagicMock(return_value={
        "active_from": None, "active_until": None, "paused_until": None,
        "resume_rule": None, "pause_reason": None,
    })
    rdb.is_routine_temporarily_inactive_meta = MagicMock(return_value=(False, None))
    rdb.set_routine_paused_until          = MagicMock()
    rdb.clear_routine_paused_until        = MagicMock()
    rdb.set_routine_active_window         = MagicMock()
    rdb.set_routine_resume_rule           = MagicMock()
    rdb.get_routine_condition             = MagicMock(return_value={})
    rdb.get_routine_conditions            = MagicMock(return_value=[])
    rdb.get_context_state                 = MagicMock(return_value=None)
    rdb.get_sentimental_info              = MagicMock(return_value={
        "sentimental": 0, "muted_from": None, "muted_until": None,
        "sentimental_send_every": 2, "sentimental_last_sent": None,
        "sentimental_silenced": False
    })
    rdb.set_routine_sentimental           = MagicMock()
    rdb.update_sentimental_last_sent      = MagicMock()
    rdb.set_sentimental_silenced          = MagicMock()
    rdb.get_routines_for_day              = MagicMock(return_value=[])
    rdb.get_eligible_preemptive_routines_for_day = MagicMock(return_value=[])
    rdb.mark_routine_triggered_today      = MagicMock()

    # ── core.* ────────────────────────────────────────────────
    for mod in [
        "core.brain", "core.graph", "core.agents",
        "core.capability_draft",
        "core.exceptions", "core.event_bus",
        "core.routine_state", "core.prompts", "core.utils",
    ]:
        sys.modules[mod] = types.ModuleType(mod)

    utils = sys.modules["core.utils"]
    utils.clean_message = MagicMock(side_effect=lambda text: str(text))
    utils.is_simple_chat_fast_path_candidate = MagicMock(return_value=False)
    utils.is_medium_web_chat_path_candidate = MagicMock(return_value=False)
    utils.is_ultra_light_ack = MagicMock(return_value=False)
    utils.get_ultra_light_ack_response = MagicMock(return_value="")
    utils.is_reply_to_recent_mail_prompt = MagicMock(return_value=False)
    utils.is_reply_to_recent_linkedin_prompt = MagicMock(return_value=False)
    utils.looks_like_terminal_linkedin_draft_result = MagicMock(return_value=False)
    utils.build_linkedin_draft_ready_reply = MagicMock(return_value="")
    utils.should_attach_linkedin_draft_reply = MagicMock(return_value=False)
    utils.looks_like_terminal_messenger_draft_result = MagicMock(return_value=False)
    utils.build_messenger_draft_ready_reply = MagicMock(return_value="")
    utils.strip_operational_assistant_paragraphs = MagicMock(side_effect=lambda text: text)

    brain = sys.modules["core.brain"]
    brain.llm             = MagicMock()
    brain.safe_llm_invoke = MagicMock(return_value=MagicMock(content="ok"))

    sys.modules["core.graph"].graph = MagicMock()
    sys.modules["core.capability_draft"].has_pending_bug_followup = lambda _state: False

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
    for mod in [
        "services.gemini", "services.embeddings",
        "services.routine_context", "services.routine_conditions",
        "services.context_extractor", "services.messenger_intent",
        "services.routine_context_clarification",
        "services.routine_context_clarification_scheduler",
    ]:
        sys.modules[mod] = types.ModuleType(mod)

    sys.modules["services.context_extractor"].extract_and_update_context_flags = MagicMock()
    sys.modules["services.routine_context_clarification_scheduler"].serialized_routine_dispatch = lambda fn: fn
    sys.modules["services.routine_context_clarification_scheduler"].drain_context_answer_dispatch = lambda: False
    # This suite owns completion, not clarification; exercise the absent-ledger
    # adapter boundary without importing real memory under its package stubs.
    sys.modules["services.routine_context_clarification"].try_context_question_reply = (
        lambda *args, **kwargs: types.SimpleNamespace(consumed=False)
    )
    sys.modules["services.messenger_intent"].classify_messenger_intent = MagicMock(return_value=None)
    sys.modules["services.messenger_intent"].is_draft_offer_acceptance = MagicMock(return_value=False)
    sys.modules["services.messenger_intent"].MESSENGER_ROUTINE_DRAFT_OFFER_MARKER = (
        "[MESSENGER_ROUTINE_DRAFT_OFFER_ACCEPTED]"
    )

    sys.modules["services.routine_context"].build_runtime_routine_context = MagicMock(return_value={
        "today": "2026-06-17",
        "kid1_away_from_home": False,
        "football_season": True,
        "school_open": True,
        "current_shift": None,
        "partner_work_mode": "office"
    })
    sys.modules["services.gemini"].safe_gemini_call = MagicMock(return_value="ok")
    sys.modules["services.embeddings"].embeddings   = MagicMock()
    sys.modules["services.routine_conditions"].evaluate_routine_condition = MagicMock(
        return_value={"allowed": True, "reason": None}
    )
    sys.modules["services.routine_conditions"].evaluate_routine_conditions = MagicMock(
        return_value={"allowed": True, "results": [], "matched_count": 0, "failed_count": 0}
    )

    from services.routine_completion_helper import RoutineSelection
    import services.routine_completion_selector
    services.routine_completion_selector.select_routine = MagicMock(
        return_value=RoutineSelection(action="none", routine_id=None)
    )

    # ── tools.* ───────────────────────────────────────────────
    for mod in ["tools", "tools.telegram", "tools.system"]:
        sys.modules[mod] = types.ModuleType(mod)
    tg = sys.modules["tools.telegram"]
    tg.send_telegram_msg      = MagicMock()
    tg.send_telegram_voice    = MagicMock()
    tg.send_telegram_msg_full = MagicMock()
    sys.modules["tools.system"]._CURRENT_CHANNEL = None

    # ── python-telegram-bot ───────────────────────────────────
    for mod in ["telegram", "telegram.ext"]:
        sys.modules[mod] = types.ModuleType(mod)


def setup_module(module):
    """Snapshot + stub + import (execution phase only, not collection)."""
    global bot
    _ORIGINAL_MODULES.update({name: sys.modules.get(name) for name in _STUB_MODULE_NAMES})
    _stub_modules()
    # Force reload of core.i18n and clients.telegram_bot
    if "core.i18n" in sys.modules:
        _ORIGINAL_MODULES["core.i18n"] = sys.modules.pop("core.i18n")
    if "clients.telegram_bot" in sys.modules:
        _ORIGINAL_MODULES["clients.telegram_bot"] = sys.modules.pop("clients.telegram_bot")

    import clients.telegram_bot as _bot_module
    bot = _bot_module


def teardown_module(module):
    """Restore sys.modules so stubs don't leak into other test files."""
    global bot
    for name in _STUB_MODULE_NAMES:
        original = _ORIGINAL_MODULES.get(name)
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original
    sys.modules.pop("clients.telegram_bot", None)
    bot = None


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _reset_mocks():
    """Reset routine-related mocks before each test."""
    rdb = sys.modules["memory.routine_db"]
    for name in ("confirm_routine", "decay_routine", "mark_routine_responded",
                  "remove_pending_confirmation", "get_eligible_preemptive_routines_for_day",
                  "get_active_routine_catalog",
                  "mark_routine_triggered_today", "mark_routine_acknowledged",
                 "acknowledge_pending_draft_offer",
                 "record_routine_skip_today", "pause_routine_indefinitely"):
        getattr(rdb, name).reset_mock()

    sys.modules["memory.event_log"].log_event.reset_mock()
    sys.modules["core.event_bus"].bus.reset_mock()
    sys.modules["tools.telegram"].send_telegram_msg.reset_mock()
    selector = sys.modules["services.routine_completion_selector"].select_routine
    selector.reset_mock()
    selector.side_effect = None
    bot.pending_reflection_confirmations = {}
    bot.pending_exec_command = None


def _run_handle_message(
    text,
    pending=None,
    today_routines=None,
    catalog_routines=None,
    selector_return=None,
    selector_returns=None,
    pending_reflections=None,
    pending_command=None,
    active_draft_status=(False, "missing", None),
    graph_reply="Natural graph reply.",
    output_calls=None,
    history_writer=None,
    selector_callback=None,
    context_builder=None,
    handle_kwargs=None,
    voice_call=None,
):
    """
    Call ``bot.handle_message`` with controlled state.

    - ``requests.post`` → raise AssertionError (no real HTTP).
    - ``graph.stream`` → raise AssertionError (no fall-through to graph).
    - Patches ``send_telegram_msg`` on the bot module to capture calls.
    """
    _reset_mocks()

    rdb = sys.modules["memory.routine_db"]
    rdb.get_eligible_preemptive_routines_for_day.return_value = today_routines or []
    rdb.get_active_routine_catalog.return_value = catalog_routines or []

    selector_mod = sys.modules["services.routine_completion_selector"]
    if selector_returns is None:
        selector_mod.select_routine.return_value = selector_return
    else:
        selector_mod.select_routine.side_effect = selector_returns
    if selector_callback is not None:
        selector_mod.select_routine.side_effect = selector_callback

    bot.pending_routine_confirmations = dict(pending or {})
    bot.pending_reflection_confirmations = dict(pending_reflections or {})
    bot.pending_exec_command = pending_command

    sent = []

    graph_mock = sys.modules["core.graph"].graph
    graph_mock.stream = MagicMock(return_value=[{
        "Chat_Agent": {"messages": [types.SimpleNamespace(
            content=graph_reply, tool_calls=None, type="ai"
        )]}
    }])

    def _requests_post_trap(*a, **kw):
        raise AssertionError("Real requests.post was called — test isolation breach")

    def _graph_trap(*a, **kw):
        raise AssertionError("Graph was invoked — handled completion must return early")

    with (
        patch("requests.post", side_effect=_requests_post_trap),
        patch("tools.telegram.send_telegram_msg", side_effect=lambda m, **kw: sent.append(m)),
        patch.object(bot, "send_telegram_msg", side_effect=lambda m, **kw: sent.append(m), create=True),
        patch.object(bot, "bus", sys.modules["core.event_bus"].bus),
        patch.object(bot, "log_event", sys.modules["memory.event_log"].log_event),
        patch.object(bot, "_build_fast_chat_context", side_effect=context_builder, return_value=([], MagicMock(content=text))),
        patch.object(bot, "_append_to_analytics_log", side_effect=history_writer or (lambda *args, **kwargs: 1)),
        patch.object(bot, "_cache_bot_message", create=True),
        patch.object(bot, "_safe_active_draft_status", return_value=active_draft_status),
        patch.object(
            bot,
            "_send_photo_to_telegram",
            side_effect=lambda path, chat_id: (
                output_calls.append(("photo", path)) if output_calls is not None else None
            ),
        ),
        patch(
            "tools.telegram.send_telegram_document",
            side_effect=lambda path, **kwargs: (
                output_calls.append(("file", path)) if output_calls is not None else None
            ),
            create=True,
        ),
    ):
        try:
            if voice_call is not None:
                target, args, kwargs = voice_call
                target(*args, **kwargs)
            else:
                bot.handle_message(text, "123456", **(handle_kwargs or {}))
        except AssertionError as e:
            if "Graph was invoked" in str(e) or "requests.post" in str(e):
                raise
            # Other AssertionErrors from internal logic are acceptable.

    return sent


def _poll_text_turns(messages):
    """Use real polling with synthetic provider updates, without spawning workers."""
    stopped = threading.Event()
    turns = []
    def fetch(*args, **kwargs):
        stopped.set()
        return types.SimpleNamespace(status_code=200, json=lambda: {
            "result": [{"update_id": i + 1, "message": message}
                       for i, message in enumerate(messages)]})
    def worker(*, target, args, kwargs=None, daemon=False):
        return types.SimpleNamespace(start=lambda: turns.append((target, args, kwargs or {})))
    with (
        patch.object(bot, "shutdown_event", stopped),
        patch.object(bot.config, "USER_NAME", "Owner", create=True),
        patch("requests.get", side_effect=fetch),
        patch("requests.post", return_value=types.SimpleNamespace(status_code=200)),
        patch.object(bot.threading, "Thread", side_effect=worker),
        patch.object(bot, "_consume_pending_georgian", return_value=False),
        patch.object(bot, "_consume_pending_partner", return_value=False),
        patch.object(bot, "handle_external_admin_command", return_value=None),
    ):
        bot.run_polling()
    return turns


@pytest.mark.parametrize("reply,expected", [
    ({"chat": {"id": 123456}, "message_id": 41}, "41"),
    ({"chat": {"id": 123456}, "message_id": True}, ""),
    ({"chat": {"id": 123456}, "message_id": 0}, ""),
    ({"chat": {"id": 123456}, "message_id": "41"}, ""),
    ({"chat": {"id": 999}, "message_id": 41}, ""),
    ({"message_id": 41}, ""),
    (None, ""),
])
def test_polling_carries_exact_reply_without_implicit_fallback(reply, expected):
    """Dropping reply metadata must not turn an explicit reply into today's yes."""
    turns = _poll_text_turns([{"chat": {"id": 123456}, "text": "ναι",
                              "reply_to_message": reply}])
    assert len(turns) == 1
    target, args, kwargs = turns[0]
    assert target is bot.handle_message
    assert args == ("ναι", "123456")
    assert kwargs == {"reply_event_id": expected}


def test_polling_does_not_dispatch_other_chat_reply():
    """The existing owner boundary still stops foreign incoming turns."""
    assert _poll_text_turns([{"chat": {"id": 999}, "text": "ναι",
        "reply_to_message": {"chat": {"id": 999}, "message_id": 41}}]) == []


def test_polling_external_reply_cannot_become_implicit_routine_feedback():
    """A Telegram external reply has no same-chat delivered question identity."""
    turns = _poll_text_turns([{"chat": {"id": 123456}, "text": "ναι",
        "external_reply": {"chat": {"id": 999}, "message_id": 41}}])
    assert turns[0][2] == {"reply_event_id": ""}


@pytest.mark.parametrize("input_kind", ["text", "voice"])
@pytest.mark.parametrize("reply_id", ["41", "99", "", None])
def test_telegram_exact_reply_updates_only_the_delivered_occurrence(tmp_path, reply_id, input_kind):
    """Real adapter/history/ledger must preserve today when replying to yesterday."""
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
    from services.routine_completion_helper import DatedRoutineSelection
    zone = ZoneInfo("Europe/Athens")
    yesterday = datetime(2026, 10, 6, 9, tzinfo=zone)
    now = datetime(2026, 10, 7, 9, tzinfo=zone)
    routine_path = tmp_path / "dated.db"
    def connect():
        return sqlite3.connect(routine_path)
    with connect() as conn:
        conn.execute("""CREATE TABLE routines (id INTEGER PRIMARY KEY, event_name TEXT,
            notify_cooldown_hours REAL, explicit_skip_streak INTEGER,
            unanswered_reminder_streak INTEGER, last_triggered TEXT, confidence REAL)""")
        conn.execute("INSERT INTO routines VALUES (11, 'rabbit', 0, 0, 0, NULL, 1.0)")
    ledger = RoutineFeedbackStore(connect)
    ledger.initialize()
    ledger.record_delivery(11, yesterday.date(), at=yesterday, receipt_id="41",
                           question="Did you clean it?", channel="telegram")
    ledger.record_delivery(11, now.date(), at=now, receipt_id="42",
                           question="Did you clean it?", channel="telegram")
    history = str(tmp_path / "history.db")
    def save(role, content, **kwargs):
        return real_append_message(role=role, content=content, channel="telegram", db_path=history)["rowid"]
    classified_questions = []
    def classify(*args, **kwargs):
        classified_questions.append(kwargs["pending_question"].event_id)
        assert reply_id in ("41", None), "Unknown explicit replies must not reach the model"
        assert kwargs["pending_question"].event_id == ("41" if reply_id else "42")
        return DatedRoutineSelection("complete", 11, yesterday.date() if reply_id else now.date())
    handler = PersistedRoutineFeedbackHandler(store=ledger, selector=classify,
        clock=lambda: now, channel="telegram", conversation_db_path=history, trusted_owner=True)
    message = {"chat": {"id": 123456}, "text": "ναι"}
    if input_kind == "voice":
        message.pop("text")
        message["voice"] = {"file_id": "synthetic-voice", "duration": 1, "mime_type": "audio/ogg"}
    if reply_id is not None:
        message["reply_to_message"] = {"chat": {"id": 123456},
            "message_id": int(reply_id) if reply_id else True}
    turns = _poll_text_turns([message])
    assert len(turns) == 1
    assert turns[0][0] is (bot.handle_message if input_kind == "text" else bot.handle_voice)
    class VoiceAdapter:
        def transcribe_audio(self, data, *, mime_type):
            assert data == b"synthetic-ogg" and mime_type == "audio/ogg"
            return "ναι"
    def download(url, **kwargs):
        assert "api.telegram.org" in url
        return types.SimpleNamespace(content=b"synthetic-ogg", json=lambda: {
            "result": {"file_path": "voice/synthetic.ogg"}})
    with (
        patch.object(bot, "_persisted_routine_feedback_handler", handler),
        patch.object(bot.os, "getcwd", return_value=str(tmp_path)),
        patch("requests.get", side_effect=download),
        patch.object(sys.modules["core.brain"], "get_voice_provider_adapter",
                     return_value=VoiceAdapter(), create=True),
        patch.object(bot, "_handle_transcribed_voice", return_value=False),
    ):
        _run_handle_message("ναι", history_writer=save, handle_kwargs=turns[0][2],
                            voice_call=turns[0] if input_kind == "voice" else None)
    assert [row.feedback for row in ledger.occurrences(11)] == [
        "complete" if reply_id == "41" else None,
        "complete" if reply_id is None else None]
    assert classified_questions == (["41"] if reply_id == "41" else ["42"] if reply_id is None else [])
    with connect() as conn:
        assert conn.execute("SELECT last_triggered FROM routines").fetchone()[0] is None
    sys.modules["memory.routine_db"].confirm_routine.assert_not_called()
    assert [row["role"] for row in real_load_messages(db_path=history)] == ["user", "ai"]
    if input_kind == "voice":
        assert list((tmp_path / "telegram_uploads").glob("*.ogg")) == []


@pytest.mark.parametrize("has_context", [False, True])
def test_telegram_persisted_feedback_hook_never_runs_legacy_completion(tmp_path, has_context):
    """The opt-in path uses the actual rowid, then continues normal chat once."""
    path = str(tmp_path / "conversation.db")
    context = bot.SystemMessage(content="verified yesterday") if has_context else None
    handler = MagicMock(return_value=context)
    def save(role, content, **kwargs):
        return real_append_message(role=role, content=content, channel="telegram", db_path=path)["rowid"]
    with patch.object(bot, "_persisted_routine_feedback_handler", handler, create=True):
        _run_handle_message("Χθες καθάρισα το κουνέλι", history_writer=save,
            today_routines=[{"id": 5, "event": "routine"}],
            selector_return=types.SimpleNamespace(action="complete", routine_id=5))
    handler.assert_called_once_with("Χθες καθάρισα το κουνέλι", {
        "rowid": 1, "role": "user", "content": "Χθες καθάρισα το κουνέλι", "channel": "telegram",
    })
    sys.modules["services.routine_completion_selector"].select_routine.assert_not_called()
    sys.modules["memory.routine_db"].mark_routine_triggered_today.assert_not_called()
    states = sys.modules["core.graph"].graph.stream.call_args.args[0]
    if context is not None:
        assert context in states["messages"]
    assert [row["role"] for row in real_load_messages(db_path=path)] == ["user", "ai"]


def test_telegram_consumed_context_reply_never_reaches_dated_feedback(tmp_path):
    """The context acknowledgement owns the saved turn and bypasses routine inference."""
    path = str(tmp_path / "context-history.db")
    handler = MagicMock()
    def save(role, content, **kwargs):
        return real_append_message(role=role, content=content, channel="telegram", db_path=path)["rowid"]
    def deliver(content, *args, **kwargs):
        save("assistant", content)
        return "context-receipt"
    with (
        patch.object(sys.modules["services.routine_context_clarification"], "try_context_question_reply",
            return_value=types.SimpleNamespace(consumed=True, reply="Context recorded")),
        patch.object(bot, "_persisted_routine_feedback_handler", handler),
        patch.object(bot, "_send_and_record_assistant", side_effect=deliver),
    ):
        _run_handle_message("Ναι είμαστε σπίτι", history_writer=save)
    handler.assert_not_called()
    sys.modules["services.routine_completion_selector"].select_routine.assert_not_called()
    sys.modules["core.graph"].graph.stream.assert_not_called()
    assert [row["role"] for row in real_load_messages(db_path=path)] == ["user", "assistant"]


def test_telegram_dated_handler_authorizes_local_draft_not_send():
    """Graph preparation keeps the exact offer and never confirms completion."""
    from services.matrix_routine_completion import MatrixRoutineDraftOffer
    context = bot.SystemMessage(content="trusted local draft offer")
    offered = MatrixRoutineDraftOffer(5, datetime(2026, 10, 7, 9), "Message Sofia", context)
    with patch.object(bot, "_persisted_routine_feedback_handler", lambda *a: offered):
        _run_handle_message("Ετοίμασέ το")
    state = sys.modules["core.graph"].graph.stream.call_args.args[0]
    assert state.get("routine_draft_offer_authorized") is True
    assert context in state["messages"]
    sys.modules["memory.routine_db"].confirm_routine.assert_not_called()
    sys.modules["memory.routine_db"].acknowledge_pending_draft_offer.assert_not_called()


def test_telegram_routine_selector_sees_persisted_input_once(tmp_path: Path) -> None:
    """The real Telegram handler persists input before classification, once."""
    from services.routine_completion_helper import RoutineSelection

    db_path = str(tmp_path / "conversation.db")
    user_rows = []

    def save(role: str, text: str, **kwargs: object) -> int:
        """Persist through the actual history abstraction, never the owner's DB."""
        saved = real_append_message(role="assistant" if role == "ai" else role,
                                    content=text, channel="telegram", db_path=db_path)
        if role == "user":
            user_rows.append(saved)
        return saved["rowid"]

    def select(*args: object, **kwargs: object) -> RoutineSelection:
        """Inspect persisted input before returning a controlled model result."""
        assert len(user_rows) == 1
        rows = real_load_messages(db_path=db_path)
        assert rows[-1]["rowid"] == user_rows[0]["rowid"]
        assert rows[-1]["content"] == "I completed it today"
        return RoutineSelection(action="complete", routine_id=5)

    _run_handle_message("I completed it today", today_routines=[{"id": 5, "event": "dynamic routine"}],
                        history_writer=save, selector_callback=select)
    sys.modules["memory.routine_db"].mark_routine_triggered_today.assert_called_once_with(5)
    assert len(user_rows) == 1


def test_telegram_missing_persisted_identity_stops_routine_changes() -> None:
    """No routine inference or execution may proceed without a saved input row."""
    _run_handle_message("I completed it today", today_routines=[{"id": 5, "event": "dynamic routine"}],
                        history_writer=lambda *args, **kwargs: None)
    sys.modules["services.routine_completion_selector"].select_routine.assert_not_called()
    rdb = sys.modules["memory.routine_db"]
    for name in ("mark_routine_triggered_today", "confirm_routine", "record_routine_skip_today", "pause_routine_indefinitely"):
        getattr(rdb, name).assert_not_called()
    sys.modules["core.graph"].graph.stream.assert_not_called()


def test_telegram_context_excludes_only_current_row_not_identical_text(tmp_path: Path) -> None:
    """The current input is not repeated in context; an identical older turn stays."""
    db_path = str(tmp_path / "conversation.db")
    real_append_message(role="user", content="same text", channel="web", db_path=db_path)
    current = real_append_message(role="user", content="same text", channel="telegram", db_path=db_path)
    history = types.ModuleType("memory.conversation_history")
    history.load_recent_context = lambda **kwargs: real_load_recent_context(db_path=db_path, **kwargs)
    with patch.dict(sys.modules, {"memory.conversation_history": history}):
        context, message = bot._build_fast_chat_context("same text", user_rowid=current["rowid"])
    assert len(context) == 1
    assert "/ web]" in context[0].content
    assert "same text" in message.content


def test_telegram_graph_gets_current_input_once_with_shared_web_history(tmp_path: Path) -> None:
    """Exercise persistence, the real context builder and graph input together."""
    db_path = str(tmp_path / "conversation.db")
    real_append_message(role="user", content="Earlier Web message", channel="web", db_path=db_path)
    history = types.ModuleType("memory.conversation_history")
    history.load_recent_context = lambda **kwargs: real_load_recent_context(db_path=db_path, **kwargs)
    builder = bot._build_fast_chat_context

    def save(role: str, text: str, **kwargs: object) -> int:
        """Write handler history to an isolated real conversation store."""
        return real_append_message(role="assistant" if role == "ai" else role,
                                   content=text, channel="telegram", db_path=db_path)["rowid"]

    with patch.dict(sys.modules, {"memory.conversation_history": history}):
        _run_handle_message("New Telegram message", history_writer=save, context_builder=builder)
    messages = sys.modules["core.graph"].graph.stream.call_args.args[0]["messages"]
    assert len(messages) == 2
    assert "Earlier Web message" in messages[0].content
    assert "New Telegram message" in messages[1].content
    users = [row for row in real_load_messages(db_path=db_path) if row["role"] == "user"]
    assert [row["content"] for row in users] == ["Earlier Web message", "New Telegram message"]


@pytest.mark.parametrize("intent", ["clarify_draft", "clear_draft", "confirm_send"])
def test_telegram_draft_intercepts_keep_single_user_record(tmp_path: Path, intent: str) -> None:
    """Draft interception reuses input; send consent only queues its approval."""
    db_path = str(tmp_path / "conversation.db")
    approval = types.ModuleType("core.approval")
    approval.save_pending = MagicMock()
    approval._notify_telegram = MagicMock()

    def save(role: str, text: str, **kwargs: object) -> int:
        """Persist intercepted messages through the real isolated history API."""
        return real_append_message(role="assistant" if role == "ai" else role,
                                   content=text, channel="telegram", db_path=db_path)["rowid"]

    with (
        patch.dict(sys.modules, {"core.approval": approval}),
        patch.object(bot, "_safe_classify_messenger_intent", return_value=types.SimpleNamespace(intent=intent)),
        patch("core.messenger_draft.clear_draft", return_value=True),
    ):
        _run_handle_message("Act on the local draft", history_writer=save,
                            active_draft_status=(True, "active", {"message": "fixture draft", "target_name": "fixture recipient"}))
    users = [row for row in real_load_messages(db_path=db_path) if row["role"] == "user"]
    assert len(users) == 1
    sys.modules["core.graph"].graph.stream.assert_not_called()
    if intent == "confirm_send":
        approval.save_pending.assert_called_once()
        assert approval.save_pending.call_args.args[0] == "execute_local_pipeline"
        approval._notify_telegram.assert_called_once()
    else:
        approval.save_pending.assert_not_called()


def test_telegram_generated_photo_marker_is_hidden_and_photo_is_sent() -> None:
    outputs = []

    sent = _run_handle_message(
        "φτιάξε εικόνα",
        graph_reply="Έτοιμη.\n[SEND_PHOTO: C:/astakos_v2/outputs/scene.jpg]",
        output_calls=outputs,
    )

    assert sent == ["Έτοιμη."]
    assert outputs == [("photo", "C:/astakos_v2/outputs/scene.jpg")]
    assert all("SEND_PHOTO" not in message for message in sent)


def test_telegram_sends_every_created_file_in_marker_order() -> None:
    outputs = []

    sent = _run_handle_message(
        "φτιάξε αρχεία",
        graph_reply=(
            "Έτοιμα.\n"
            "[CREATED_FILE: C:/astakos_v2/outputs/one.pdf]\n"
            "[CREATED_FILE: C:/astakos_v2/outputs/two.xlsx]"
        ),
        output_calls=outputs,
    )

    assert sent == ["Έτοιμα."]
    assert outputs == [
        ("file", "C:/astakos_v2/outputs/one.pdf"),
        ("file", "C:/astakos_v2/outputs/two.xlsx"),
    ]


# ─────────────────────────────────────────────────────────────
# (a) Pre-emptive selected routine
# ─────────────────────────────────────────────────────────────

def test_preemptive_completion_calls_mark_triggered():
    """Pre-emptive today-pool match ⇒ mark_routine_triggered_today(5) called."""
    from services.routine_completion_helper import RoutineSelection
    rdb = sys.modules["memory.routine_db"]

    sent = _run_handle_message(
        "πήγαμε στο σούπερ μάρκετ",
        pending=None,
        today_routines=[
            {"id": 5, "time": "15:00", "event": "Σούπερ μάρκετ",
             "type": "general", "confidence": 0.9, "mentions": 3, "state": "active"},
        ],
        selector_return=RoutineSelection(action="complete", routine_id=5),
    )

    rdb.mark_routine_triggered_today.assert_called_once_with(5)
    rdb.confirm_routine.assert_not_called()
    rdb.decay_routine.assert_not_called()
    assert len(sent) == 1  # ack message sent


def test_preemptive_completion_continues_to_graph():
    """Pre-emptive completion preserves the normal graph conversation path."""
    from services.routine_completion_helper import RoutineSelection
    graph_mock = sys.modules["core.graph"].graph
    rdb = sys.modules["memory.routine_db"]

    _run_handle_message(
        "πήγαμε στο σούπερ μάρκετ",
        pending=None,
        today_routines=[
            {"id": 5, "time": "15:00", "event": "Σούπερ μάρκετ",
             "type": "general", "confidence": 0.9, "mentions": 3, "state": "active"},
        ],
        selector_return=RoutineSelection(action="complete", routine_id=5),
    )

    rdb.mark_routine_triggered_today.assert_called_once_with(5)
    graph_mock.stream.assert_called_once()
    graph_messages = graph_mock.stream.call_args.args[0]["messages"]
    assert len(graph_messages) == 2


def test_today_acknowledgement_does_not_complete_routine() -> None:
    """A future commitment carries trusted lifecycle context without marking completion."""
    from services.routine_completion_helper import RoutineSelection
    rdb = sys.modules["memory.routine_db"]
    graph_mock = sys.modules["core.graph"].graph
    lifecycle_context = MagicMock(name="lifecycle_context")

    with patch(
        "services.routine_completion_context.build_routine_completion_context",
        return_value=lifecycle_context,
    ) as build_context:
        _run_handle_message(
            "natural future commitment",
            today_routines=[{"id": 5, "event": "Dynamic routine", "state": "active"}],
            selector_return=RoutineSelection(action="acknowledge", routine_id=5),
        )

    rdb.mark_routine_acknowledged.assert_called_once_with(5)
    rdb.mark_routine_triggered_today.assert_not_called()
    rdb.confirm_routine.assert_not_called()
    build_context.assert_called_once_with()
    graph_messages = graph_mock.stream.call_args.args[0]["messages"]
    assert lifecycle_context in graph_messages


def test_pending_messenger_offer_bare_yes_adds_trusted_draft_context() -> None:
    """One pending Messenger offer accepts bare consent without invoking the selector."""

    graph_mock = sys.modules["core.graph"].graph
    selector_mock = sys.modules["services.routine_completion_selector"].select_routine
    draft_context = types.SimpleNamespace(
        content="[MESSENGER_ROUTINE_DRAFT_OFFER_ACCEPTED]",
        type="system",
    )

    with (
        patch(
            "services.messenger_intent.is_draft_offer_acceptance",
            return_value=True,
        ),
        patch(
            "services.routine_completion_context.build_messenger_draft_offer_context",
            return_value=draft_context,
        ) as build_draft_context,
    ):
        _run_handle_message(
            "ναι",
            pending={
                5: {
                    "event": "Dinner with Partner",
                    "draft_offer": True,
                    "sent_at": datetime.now(),
                }
            },
        )

    build_draft_context.assert_called_once_with("Dinner with Partner")
    selector_mock.assert_not_called()
    graph_messages = graph_mock.stream.call_args.args[0]["messages"]
    assert draft_context in graph_messages


def test_pending_messenger_offer_natural_acceptance_adds_trusted_draft_context() -> None:
    """A natural reply to one offer authorizes a local draft through the selector."""
    from services.routine_completion_helper import RoutineSelection

    graph_mock = sys.modules["core.graph"].graph
    selector_mock = sys.modules["services.routine_completion_selector"].select_routine
    draft_context = types.SimpleNamespace(
        content="[MESSENGER_ROUTINE_DRAFT_OFFER_ACCEPTED]",
        type="system",
    )

    with (
        patch(
            "services.messenger_intent.is_draft_offer_acceptance",
            return_value=False,
        ),
        patch(
            "services.routine_completion_context.build_messenger_draft_offer_context",
            return_value=draft_context,
        ) as build_draft_context,
    ):
        _run_handle_message(
            "Ναι φίλε κάνε το πιο γλυκό",
            pending={
                5: {
                    "event": "Dinner with Partner",
                    "draft_offer": True,
                    "sent_at": datetime.now(),
                }
            },
            selector_return=RoutineSelection(action="draft", routine_id=5),
        )

    selector_mock.assert_called_once()
    sys.modules["memory.routine_db"].acknowledge_pending_draft_offer.assert_not_called()
    build_draft_context.assert_called_once_with("Dinner with Partner")
    graph_state = graph_mock.stream.call_args.args[0]
    assert graph_state["routine_draft_offer_authorized"] is True
    assert 5 in bot.pending_routine_confirmations


def test_active_draft_keeps_bare_yes_out_of_pending_offer_path() -> None:
    """An active draft takes precedence over an unrelated pending draft offer."""
    selector_mock = sys.modules["services.routine_completion_selector"].select_routine

    with patch(
            "services.routine_completion_context.build_messenger_draft_offer_context"
        ) as build_draft_context:
        _run_handle_message(
            "ναι",
            pending={
                5: {
                    "event": "Message routine",
                    "draft_offer": True,
                    "sent_at": datetime.now(),
                }
            },
            active_draft_status=(True, "active", {"message": "draft"}),
        )

    selector_mock.assert_called_once()
    build_draft_context.assert_not_called()
    sys.modules["memory.routine_db"].acknowledge_pending_draft_offer.assert_not_called()


def test_pending_partner_routine_without_draft_offer_keeps_selector_path() -> None:
    """A partner-named routine cannot convert bare consent into a draft without proof."""
    graph_mock = sys.modules["core.graph"].graph
    selector_mock = sys.modules["services.routine_completion_selector"].select_routine

    with patch(
        "services.routine_completion_context.build_messenger_draft_offer_context"
    ) as build_draft_context:
        _run_handle_message(
            "ναι",
            pending={5: {"event": "Dinner with Partner", "draft_offer": False}},
        )

    selector_mock.assert_called_once()
    build_draft_context.assert_not_called()
    graph_messages = graph_mock.stream.call_args.args[0]["messages"]
    assert all(
        "[MESSENGER_ROUTINE_DRAFT_OFFER_ACCEPTED]" not in str(
            getattr(message, "content", "")
        )
        for message in graph_messages
    )


def test_batched_pending_offer_keeps_selector_path() -> None:
    """A batch cannot convert bare consent into a Messenger draft for any routine."""
    graph_mock = sys.modules["core.graph"].graph
    selector_mock = sys.modules["services.routine_completion_selector"].select_routine

    with (
        patch(
            "services.messenger_intent.is_draft_offer_acceptance",
            return_value=True,
        ),
        patch(
            "services.routine_completion_context.build_messenger_draft_offer_context"
        ) as build_draft_context,
    ):
        _run_handle_message(
            "Î½Î±Î¹",
            pending={
                5: {"event": "Message routine", "draft_offer": True},
                6: {"event": "Other routine", "draft_offer": False},
            },
        )

    selector_mock.assert_called_once()
    build_draft_context.assert_not_called()
    graph_messages = graph_mock.stream.call_args.args[0]["messages"]
    assert all(
        "[MESSENGER_ROUTINE_DRAFT_OFFER_ACCEPTED]" not in str(
            getattr(message, "content", "")
        )
        for message in graph_messages
    )


def test_proactive_message_uses_structured_draft_offer_state() -> None:
    """Only an exact structured proactive response can arm one draft offer."""
    bot.config.USER_NAME = "User"
    with (
        patch.object(bot.core.i18n, "load_prompt", return_value="{context}"),
        patch.object(bot, "_build_proactive_memory_context", return_value=""),
        patch.object(bot, "_build_proactive_state_snapshot", return_value={}),
        patch.object(bot, "_force_proactive_skip_from_state", return_value=None),
        patch.object(bot, "_get_env_context", return_value=""),
        patch.object(
            bot,
            "safe_llm_invoke",
            return_value=types.SimpleNamespace(
                content='{"message":"Shall I prepare a draft?","offers_messenger_draft":true}'
            ),
        ),
    ):
        message, draft_offer = bot._craft_proactive_msg("Message routine", 0.9)

    assert message == "Shall I prepare a draft?"
    assert draft_offer is True


def test_proactive_unstructured_message_uses_safe_fallback() -> None:
    """Unstructured proactive prose cannot reach the user or authorize bare consent."""
    bot.config.USER_NAME = "User"
    with (
        patch.object(bot.core.i18n, "load_prompt", return_value="{context}"),
        patch.object(bot, "_build_proactive_memory_context", return_value=""),
        patch.object(bot, "_build_proactive_state_snapshot", return_value={}),
        patch.object(bot, "_force_proactive_skip_from_state", return_value=None),
        patch.object(bot, "_get_env_context", return_value=""),
        patch.object(bot, "t", return_value="Safe proactive fallback."),
        patch.object(
            bot,
            "safe_llm_invoke",
            return_value=types.SimpleNamespace(content="Remember to read your partner's message."),
        ),
    ):
        message, draft_offer = bot._craft_proactive_msg("Message routine", 0.9)

    assert message == "Safe proactive fallback."
    assert draft_offer is False


def test_proactive_prefixed_json_uses_safe_fallback() -> None:
    """Prefixed structured output never reaches the user or authorizes a draft offer."""
    bot.config.USER_NAME = "User"
    with (
        patch.object(bot.core.i18n, "load_prompt", return_value="{context}"),
        patch.object(bot, "_build_proactive_memory_context", return_value=""),
        patch.object(bot, "_build_proactive_state_snapshot", return_value={}),
        patch.object(bot, "_force_proactive_skip_from_state", return_value=None),
        patch.object(bot, "_get_env_context", return_value=""),
        patch.object(bot, "t", return_value="Safe proactive fallback."),
        patch.object(
            bot,
            "safe_llm_invoke",
            return_value=types.SimpleNamespace(
                content='Here is the JSON: {"message":"Do not expose","offers_messenger_draft":true}'
            ),
        ),
    ):
        message, draft_offer = bot._craft_proactive_msg("Message routine", 0.9)

    assert message == "Safe proactive fallback."
    assert draft_offer is False


def test_unrelated_pending_does_not_block_today_completion() -> None:
    """A pass-through pending decision still lets a later today candidate complete."""
    from services.routine_completion_helper import RoutineSelection
    rdb = sys.modules["memory.routine_db"]

    _run_handle_message(
        "natural completion message",
        pending={11: {"event": "Unrelated pending routine"}},
        today_routines=[{"id": 5, "event": "Dynamic routine", "state": "active"}],
        selector_returns=[
            RoutineSelection(action="none", routine_id=None),
            RoutineSelection(action="complete", routine_id=5),
        ],
    )

    rdb.mark_routine_triggered_today.assert_called_once_with(5)
    rdb.confirm_routine.assert_not_called()
    assert 11 in bot.pending_routine_confirmations


def test_pending_skip_today_does_not_decay_routine() -> None:
    """A same-day refusal closes the pending reminder without long-term decay."""
    from services.routine_completion_helper import RoutineSelection
    rdb = sys.modules["memory.routine_db"]

    _run_handle_message(
        "natural same-day refusal",
        pending={5: {"event": "Dynamic routine"}},
        selector_return=RoutineSelection(action="skip_today", routine_id=5),
    )

    rdb.record_routine_skip_today.assert_called_once_with(5)
    rdb.decay_routine.assert_not_called()
    assert 5 not in bot.pending_routine_confirmations


def test_today_pause_is_reversible_and_does_not_complete_routine() -> None:
    """A permanent-cancellation decision pauses instead of deleting or completing."""
    from services.routine_completion_helper import RoutineSelection
    rdb = sys.modules["memory.routine_db"]

    _run_handle_message(
        "natural permanent cancellation",
        today_routines=[{"id": 5, "event": "Dynamic routine", "state": "active"}],
        selector_return=RoutineSelection(action="pause", routine_id=5),
    )

    rdb.pause_routine_indefinitely.assert_called_once_with(5)
    rdb.mark_routine_triggered_today.assert_not_called()
    rdb.confirm_routine.assert_not_called()


def test_catalog_pause_handles_explicit_named_routine_outside_today() -> None:
    """A named routine may be permanently paused even when it is not due today."""
    from services.routine_completion_helper import RoutineSelection
    rdb = sys.modules["memory.routine_db"]

    _run_handle_message(
        "natural permanent cancellation of dynamic routine",
        today_routines=[{"id": 5, "event": "unrelated routine", "state": "active"}],
        catalog_routines=[{"id": 9, "event": "dynamic routine"}],
        selector_returns=[
            RoutineSelection(action="none", routine_id=None),
            RoutineSelection(action="pause", routine_id=9),
        ],
    )

    rdb.pause_routine_indefinitely.assert_called_once_with(9)


# ─────────────────────────────────────────────────────────────
# (b) Multiple pending + bare yes ⇒ clarification
# ─────────────────────────────────────────────────────────────

def test_multiple_pending_without_selection_passes_to_graph():
    """An ambiguous pending message does not mutate a routine or emit a canned reply."""
    rdb = sys.modules["memory.routine_db"]

    sent = _run_handle_message(
        "ναι",
        pending={
            5: {"event": "Πάρκο"},
            8: {"event": "Σούπερ μάρκετ"},
        },
    )

    rdb.confirm_routine.assert_not_called()
    rdb.decay_routine.assert_not_called()
    rdb.mark_routine_responded.assert_not_called()
    assert sent == ["Natural graph reply."]


# ─────────────────────────────────────────────────────────────
# (c) One pending + yes ⇒ confirm only that ID
# ─────────────────────────────────────────────────────────────

def test_single_pending_bare_yes_confirms_exactly_one():
    """'ναι' with 1 pending ⇒ confirm_routine(5), mark_routine_responded(5),
    remove_pending_confirmation(5). No decay."""
    from services.routine_completion_helper import RoutineSelection
    rdb = sys.modules["memory.routine_db"]

    sent = _run_handle_message(
        "ναι",
        pending={5: {"event": "Πάρκο"}},
        selector_return=RoutineSelection(action="complete", routine_id=5),
    )

    rdb.confirm_routine.assert_called_once_with(5)
    rdb.mark_routine_responded.assert_called_once_with(5)
    rdb.mark_routine_triggered_today.assert_called_once_with(5)
    rdb.remove_pending_confirmation.assert_called_once_with(5)
    rdb.decay_routine.assert_not_called()
    assert len(sent) == 1  # ack message
    assert 5 not in bot.pending_routine_confirmations


def test_single_pending_bare_no_uses_explicit_skip_today():
    """A same-day refusal skips the exact pending routine without decay."""
    from services.routine_completion_helper import RoutineSelection
    rdb = sys.modules["memory.routine_db"]

    sent = _run_handle_message(
        "όχι",
        pending={5: {"event": "Πάρκο"}},
        selector_return=RoutineSelection(action="skip_today", routine_id=5),
    )

    rdb.record_routine_skip_today.assert_called_once_with(5)
    rdb.decay_routine.assert_not_called()
    rdb.remove_pending_confirmation.assert_called_once_with(5)
    rdb.confirm_routine.assert_not_called()
    assert len(sent) == 1  # exactly one acknowledgment message
    assert 5 not in bot.pending_routine_confirmations


def test_routine_completion_skips_other_pending_confirmations() -> None:
    """One routine completion cannot also authorize reflection or executor work."""
    from services.routine_completion_helper import RoutineSelection

    sent = _run_handle_message(
        "yes",
        pending={5: {"event": "Routine"}},
        selector_return=RoutineSelection(action="complete", routine_id=5),
        pending_reflections={1: {"observation": "pending reflection"}},
        pending_command="Write-Output should-not-run",
    )

    assert 1 in bot.pending_reflection_confirmations
    assert bot.pending_exec_command == "Write-Output should-not-run"
    assert sent == ["Natural graph reply."]
# ─────────────────────────────────────────────────────────────
# (d) Partner/messenger contextual skip ⇒ return guard,
#     decide_completion never called
# ─────────────────────────────────────────────────────────────

def test_partner_contextual_skip_bypasses_decide_completion():
    """Partner/messenger skip ⇒ returns before decide_completion.
    No confirm, no decay, and the decide_completion callable is not invoked."""
    rdb = sys.modules["memory.routine_db"]

    # Patch decide_completion to detect if it is called.
    decide_spy = MagicMock(side_effect=AssertionError(
        "decide_completion should NOT be called for partner/messenger path"
    ))

    with patch("services.routine_completion_helper.decide_completion", decide_spy):
        sent = _run_handle_message(
            "ήρθαμε θάλασσα, είμαστε μαζί",
            pending={
                999: {"event": "Στείλε μήνυμα στη Partner (messenger)"},
            },
        )

    # Partner/messenger path: no decay, remove_pending, no confirm.
    rdb.decay_routine.assert_not_called()
    rdb.confirm_routine.assert_not_called()
    rdb.remove_pending_confirmation.assert_called_once_with(999)
    assert 999 not in bot.pending_routine_confirmations


# ─────────────────────────────────────────────────────────────
# Extra: requests.post trap
# ─────────────────────────────────────────────────────────────

def test_requests_post_trapped():
    """Verify that requests.post raises if somehow reached."""
    with pytest.raises(AssertionError, match="requests.post"):
        with patch("requests.post", side_effect=AssertionError("Real requests.post was called")):
            import requests
            requests.post("https://api.telegram.org/anything")
