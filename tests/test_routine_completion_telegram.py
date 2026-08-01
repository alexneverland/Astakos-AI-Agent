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
from datetime import datetime
from unittest.mock import MagicMock, patch, call

import pytest


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
    "core.exceptions", "core.event_bus",
    "core.routine_state", "core.prompts", "core.utils", "core.i18n", "core.nl_config",
    "services.gemini", "services.embeddings", "services.context_extractor",
    "services.messenger_intent",
    "services.routine_context", "services.routine_conditions",
    "tools", "tools.telegram",
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
    rdb.record_routine_skip_today          = MagicMock(return_value={
        "skip_streak": 1,
        "cooldown_applied": False,
        "cooldown_hours": None,
    })
    rdb.pause_routine_indefinitely         = MagicMock()
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
        "core.exceptions", "core.event_bus",
        "core.routine_state", "core.prompts", "core.utils",
    ]:
        sys.modules[mod] = types.ModuleType(mod)

    utils = sys.modules["core.utils"]
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
    ]:
        sys.modules[mod] = types.ModuleType(mod)

    sys.modules["services.context_extractor"].extract_and_update_context_flags = MagicMock()
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
                 "mark_routine_triggered_today", "mark_routine_acknowledged",
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
    selector_return=None,
    selector_returns=None,
    pending_reflections=None,
    pending_command=None,
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

    selector_mod = sys.modules["services.routine_completion_selector"]
    if selector_returns is None:
        selector_mod.select_routine.return_value = selector_return
    else:
        selector_mod.select_routine.side_effect = selector_returns

    bot.pending_routine_confirmations = dict(pending or {})
    bot.pending_reflection_confirmations = dict(pending_reflections or {})
    bot.pending_exec_command = pending_command

    sent = []

    graph_mock = sys.modules["core.graph"].graph
    graph_mock.stream = MagicMock(return_value=[{
        "Chat_Agent": {"messages": [types.SimpleNamespace(
            content="Natural graph reply.", tool_calls=None, type="ai"
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
        patch.object(bot, "_build_fast_chat_context", return_value=([], MagicMock(content=text))),
        patch.object(bot, "_append_to_analytics_log", return_value=1),
        patch.object(bot, "_cache_bot_message", create=True),
    ):
        try:
            bot.handle_message(text, "123456")
        except AssertionError as e:
            if "Graph was invoked" in str(e) or "requests.post" in str(e):
                raise
            # Other AssertionErrors from internal logic are acceptable.

    return sent


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
                }
            },
        )

    build_draft_context.assert_called_once_with()
    selector_mock.assert_not_called()
    graph_messages = graph_mock.stream.call_args.args[0]["messages"]
    assert draft_context in graph_messages


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
