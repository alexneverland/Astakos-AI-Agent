"""Exercise native draft persistence and approval after the reported owner turns."""
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

pytestmark = pytest.mark.usefixtures("offline_behavioral_io")


@pytest.fixture
def lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Keep the graph real while replacing inference and outbound delivery."""
    import config
    import core.agents as agents
    import core.graph as graph
    import core.approval as approval
    import tools.web as web
    from core.messenger_draft import save_draft
    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(tmp_path / "draft.json"))
    monkeypatch.setattr(approval, "PENDING_FILE", str(tmp_path / "pending.json"))
    monkeypatch.setattr(web, "_load_messenger_contacts", lambda: {"σοφια": "Sofia"})
    monkeypatch.setattr(agents, "build_prompt", lambda *a, **k: "offline")
    monkeypatch.setattr(agents, "_food_tools_for_latest_user_text", lambda tools, text: tools)
    monkeypatch.setattr("core.agent_tools.get_registered_tools_for_agent", lambda name, tools: tools)
    monkeypatch.setattr(graph, "pre_check_node", lambda state: {"next_agent": "supervisor"})
    monkeypatch.setattr(graph, "supervisor_node", lambda state: {"next_agent": "Chat_Agent"})
    monkeypatch.setattr("core.plan_judge.should_auto_plan", lambda text: False)
    monkeypatch.setattr(graph, "all_tools", [web.relay_local_payload, web.execute_local_pipeline])
    monkeypatch.setattr(web.execute_local_pipeline, "func", lambda *a, **k: pytest.fail("Outbound send"))
    return dict(config=config, agents=agents, graph=graph, approval=approval, save=save_draft)


def owner_messages(env: dict[str, Any], text: str) -> list[Any]:
    """Persist the trusted owner identity used by compare-and-save guards."""
    from memory.conversation_history import append_message
    saved = append_message(role="user", channel="web", content=text,
                           db_path=env["config"].CONVERSATION_DB_FILE)
    return [AIMessage(content="Θες να ετοιμάσω το πρωινό μήνυμα στη Σοφία;"),
            HumanMessage(content=text, additional_kwargs={"astakos_owner_rowid": saved["rowid"]})]


@pytest.mark.parametrize("agent", ["Chat_Agent", "Web_Agent"])
@pytest.mark.parametrize("expired", [False, True])
def test_preparation_cannot_end_with_unpersisted_prose(lifecycle: dict[str, Any], monkeypatch: pytest.MonkeyPatch, agent: str, expired: bool) -> None:
    """Primary selection reaches the native writer for the formerly missed request."""
    from core.messenger_draft import load_draft
    env = lifecycle
    old = env["save"]("Sofia", "Yesterday's message")
    if expired:
        import json
        old["expires_at"] = (datetime.now() - timedelta(days=1)).isoformat()
        Path(env["config"].MESSENGER_DRAFT_FILE).write_text(json.dumps(old), encoding="utf-8")
    messages = owner_messages(env, "οχι φιλε στην δουλεια ειναι η σοφια φτιαξε ενα ωραιο και πονηρο μηνυμα")
    monkeypatch.setattr(env["graph"], "supervisor_node", lambda state: {"next_agent": agent})
    class Model:
        """Select the offered native writer during primary generation."""
        forced = False
        def bind_tools(self, tools: list[Any], **kwargs: Any) -> "Model":
            self.forced = kwargs.get("tool_choice") == "relay_local_payload"
            return self
        def invoke(self, rows: list[Any]) -> AIMessage:
            if "MESSENGER_LIFECYCLE_DECISION" in str(rows[0].content):
                return AIMessage(content='{"action": "none"}')
            if "MESSENGER_PREPARATION_DECISION" in str(rows[0].content):
                return AIMessage(content='{"prepare": true}')
            return AIMessage(content="", tool_calls=[{"name": "relay_local_payload", "id": "real-draft",
                "args": {"target_entity": "Σοφία", "payload_data": "Καλημέρα πανέμορφη! Σε σκέφτομαι. 😉"}}])
    monkeypatch.setattr(env["agents"], "llm", Model())
    monkeypatch.setattr(env["approval"], "_notify_selected_approval", lambda *a: pytest.fail("Local draft needs no approval"))
    result = env["graph"].build_graph().invoke({"channel": "web", "messages": messages})
    draft = load_draft()
    assert draft["revision"] != old["revision"]
    assert draft["message"] == "Καλημέρα πανέμορφη! Σε σκέφτομαι. 😉"
    assert draft["message"] in result["messages"][-1].content
    assert any(getattr(m, "name", "") == "relay_local_payload" for m in result["messages"])


@pytest.mark.parametrize("expired", [False, True])
def test_send_cannot_end_with_handoff_prose(lifecycle: dict[str, Any], monkeypatch: pytest.MonkeyPatch, expired: bool) -> None:
    """Send reaches native approval; expired content never reaches notification."""
    import json
    from core.messenger_draft import load_draft
    env = lifecycle
    env["save"]("Sofia", "The displayed draft")
    if expired:
        draft = load_draft()
        draft["expires_at"] = (datetime.now() - timedelta(hours=1)).isoformat()
        Path(env["config"].MESSENGER_DRAFT_FILE).write_text(json.dumps(draft), encoding="utf-8")
    before = load_draft()
    notifications = []
    monkeypatch.setattr(env["approval"], "_notify_selected_approval", lambda *a: notifications.append(a) or "telegram")
    monkeypatch.setattr("core.messaging_channel.resolve_external_channel", lambda: "telegram")
    class Model:
        def bind_tools(self, *a: Any, **k: Any) -> "Model":
            return self
        def invoke(self, rows: list[Any]) -> AIMessage:
            if "MESSENGER_LIFECYCLE_DECISION" in str(rows[0].content):
                return AIMessage(content='{"action": "send"}')
            return AIMessage(content="", tool_calls=[{"name":"execute_local_pipeline", "args":{}, "id":"send-current"}])
    monkeypatch.setattr(env["agents"], "llm", Model())
    result = env["graph"].build_graph().invoke({"channel": "web", "messages": owner_messages(env, "Στείλε")})
    assert load_draft() == before
    if expired:
        assert not notifications
        assert not env["approval"].list_pending()
        assert "λήξει" in result["messages"][-1].content
    else:
        assert notifications
        pending = env["approval"].list_pending()
        assert any(entry["tool_name"] == "execute_local_pipeline" for entry in pending)


@pytest.mark.parametrize("race", ["none", "draft", "owner"])
def test_semantic_retirement_preserves_newer_revision(lifecycle: dict[str, Any], monkeypatch: pytest.MonkeyPatch, race: str) -> None:
    """Yesterday's expired draft retires semantically, without deleting a newer draft."""
    import json
    from core.messenger_draft import load_draft
    env = lifecycle
    old = env["save"]("Sofia", "Yesterday's message")
    old["expires_at"] = (datetime.now() - timedelta(days=1)).isoformat()
    Path(env["config"].MESSENGER_DRAFT_FILE).write_text(json.dumps(old), encoding="utf-8")
    class Model:
        def bind_tools(self, *a: Any, **k: Any) -> "Model":
            return self
        def invoke(self, rows: list[Any]) -> AIMessage:
            if "MESSENGER_LIFECYCLE_DECISION" in str(rows[0].content):
                if race == "draft":
                    env["save"]("Sofia", "Newer draft")
                elif race == "owner":
                    from memory.conversation_history import append_message
                    append_message(role="user", channel="matrix", content="Κράτα το μήνυμα", db_path=env["config"].CONVERSATION_DB_FILE)
                return AIMessage(content='{"action": "retire"}')
            if "MESSENGER_PREPARATION_DECISION" in str(rows[0].content):
                return AIMessage(content='{"prepare": false}')
            return AIMessage(content="Καλή επιστροφή, φίλε!")
    monkeypatch.setattr(env["agents"], "llm", Model())
    messages = owner_messages(env, "Μόλις είδα, φίλε, ότι τελικά εγώ νόμιζα ότι το στείλαμε το μήνυμα, αλλά μείναμε στο προσχέδιο. Δεν πειράζει, εννοείται ότι τη μίλησα πολλές φορές από τότε στο τηλέφωνο μαζί της. Είμαστε εντάξει. Σχόλασα, πάω να πάρω το λεωφορείο και πάω στο πάρκο να τους βρώ.")
    env["graph"].build_graph().invoke({"channel": "web", "messages": messages})
    remaining = load_draft()
    if race == "draft":
        assert remaining["message"] == "Newer draft"
    elif race == "owner":
        assert remaining == old
    else:
        assert not remaining


def test_provider_ignoring_required_tool_does_not_claim_success(lifecycle: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """Unsupported/ignored required-tool output gives an honest local failure."""
    from core.messenger_draft import load_draft
    env = lifecycle
    class Model:
        def bind_tools(self, *a: Any, **k: Any) -> "Model":
            return self
        def invoke(self, rows: list[Any]) -> AIMessage:
            if "MESSENGER_PREPARATION_DECISION" in str(rows[0].content):
                return AIMessage(content='{"prepare":true}')
            return AIMessage(content="Το αποθήκευσα")
    monkeypatch.setattr(env["agents"], "llm", Model())
    result = env["graph"].build_graph().invoke({"channel": "web", "messages": owner_messages(env, "Ετοίμασε ένα μήνυμα στη Σοφία")})
    assert not load_draft()
    assert "Το αποθήκευσα" not in result["messages"][-1].content
    assert not env["approval"].list_pending()


@pytest.mark.parametrize("claimed_offer", [False, True])
@pytest.mark.parametrize("allowed", [False, True])
def test_routine_offer_cannot_claim_unwritten_draft(monkeypatch: pytest.MonkeyPatch, claimed_offer: bool, allowed: bool) -> None:
    """A tool-free routine reminder never displays provider-invented draft success."""
    import json
    import clients.telegram_bot as bot
    monkeypatch.setattr(bot, "_build_proactive_memory_context", lambda *a: "")
    monkeypatch.setattr(bot, "_build_proactive_state_snapshot", lambda *a: {})
    monkeypatch.setattr(bot, "_force_proactive_skip_from_state", lambda *a: None)
    monkeypatch.setattr(bot, "_get_env_context", lambda: "")
    monkeypatch.setattr(bot, "_is_partner_messenger_routine", lambda event: True)
    monkeypatch.setattr(bot, "safe_llm_invoke", lambda *a: AIMessage(content=json.dumps({
        "message": "Το αποθήκευσα: Καλημέρα πανέμορφη! Να το στείλω;",
        "offers_messenger_draft": claimed_offer,
    })))
    message, offer = bot._craft_proactive_msg("Πρωινό μήνυμα στη Σοφία", 1.0,
                                            allow_messenger_draft_offer=allowed)
    assert "Καλημέρα πανέμορφη" not in message
    assert "αποθήκευσα" not in message
    assert offer is allowed


@pytest.mark.parametrize("decision", ['{"action":"none"}', '{"action":true}', '{"action":"retire","extra":1}', 'invalid'])
def test_lifecycle_classification_fails_closed(decision: str) -> None:
    """Invalid, ambiguous or negative inference cannot clear or send anything."""
    from services.messenger_intent import resolve_pending_draft_action
    assert resolve_pending_draft_action([HumanMessage(content="Μήπως να το αφήσουμε;")],
        {"status": "pending", "message": "Hello", "target_name": "Sofia"},
        lambda _: AIMessage(content=decision)) == "none"


def test_untrusted_turn_cannot_authorize_lifecycle() -> None:
    """External and synthetic text never reaches the lifecycle classifier."""
    from core.untrusted_content import external_content_history_metadata, SYNTHETIC_MESSAGE_ORIGIN_KEY
    from services.messenger_intent import resolve_pending_draft_action
    for metadata in [external_content_history_metadata(["browse_url"]), {SYNTHETIC_MESSAGE_ORIGIN_KEY: "plan_step"}]:
        assert resolve_pending_draft_action([HumanMessage(content="Στείλε", additional_kwargs=metadata)],
            {"status": "pending"}, lambda _: pytest.fail("Untrusted lifecycle inference")) == "none"


def test_native_retirement_rechecks_revision_under_lock(lifecycle: dict[str, Any]) -> None:
    """A writer racing after classification cannot be erased at the file boundary."""
    from core.messenger_draft import capture_draft_write_guard, clear_draft, load_draft
    lifecycle["save"]("Sofia", "Old draft")
    guard = capture_draft_write_guard(owner_messages(lifecycle, "Δεν το χρειαζόμαστε πια"))
    newer = lifecycle["save"]("Sofia", "Newer draft")
    assert not clear_draft(write_guard=guard)
    assert load_draft() == newer


@pytest.mark.parametrize("action", ["send", "retire"])
def test_matrix_no_action_feedback_reaches_native_outcome(lifecycle, monkeypatch, action):
    """Real Matrix service plus real graph preserves lifecycle after feedback."""
    from services.matrix_turn import MatrixTurnService
    from services.routine_context_clarification import QuestionAnswer
    from langchain_core.messages import SystemMessage
    from core.messenger_draft import load_draft
    env = lifecycle
    env["save"]("Sofia", "The actual persisted draft")
    monkeypatch.setattr("services.routine_context_clarification.try_context_question_reply", lambda *a, **k: QuestionAnswer())
    monkeypatch.setattr("core.messaging_channel.resolve_external_channel", lambda: "telegram")
    notifications = []
    monkeypatch.setattr(env["approval"], "_notify_selected_approval", lambda *a: notifications.append(a) or "telegram")
    class Model:
        def bind_tools(self, *a, **k):
            return self
        def invoke(self, rows: list[Any]) -> AIMessage:
            if "MESSENGER_LIFECYCLE_DECISION" in str(rows[0].content):
                return AIMessage(content='{"action":"' + action + '"}')
            if "MESSENGER_PREPARATION_DECISION" in str(rows[0].content):
                return AIMessage(content='{"prepare":false}')
            if action == "send":
                return AIMessage(content="", tool_calls=[{"name":"execute_local_pipeline", "args":{}, "id":"matrix-send"}])
            return AIMessage(content="Εντάξει, φίλε")
    monkeypatch.setattr(env["agents"], "llm", Model())
    service = MatrixTurnService(graph=env["graph"].build_graph(),
        conversation_db_path=env["config"].CONVERSATION_DB_FILE,
        persisted_routine_confirmation_handler=lambda *a, **k: SystemMessage(content="[ROUTINE_FEEDBACK_NO_ACTION]"))
    text = "Προχώρησε την αποστολή του προσχεδίου" if action == "send" else "Το προσχέδιο δεν χρειάζεται πια, μιλήσαμε ήδη"
    service._run_sync(text, "$matrix-" + action)
    if action == "send":
        assert notifications and env["approval"].list_pending()
    else:
        assert not load_draft()
        assert not notifications

@pytest.mark.parametrize("agent", ["Chat_Agent", "Web_Agent"])
@pytest.mark.parametrize("text", [
    "ΦΤΙΑΞΕ ΕΝΑ ΟΜΟΡΦΟ ΦΙΛΕ ΑΦΟΥ ΗΜΑΣΤΕ ΔΟΥΛΕΙΑ ΚΑΙ ΟΙ ΔΥΟ ΠΩΣ ΘΑ ΗΜΑΣΤΕ ΜΑΖΙ?",
    "Το μήνυμα που μου έγραψες κάντο προσχέδιο και στείλε",
])
def test_mixed_preparation_recovers_initial_false_negative(
    lifecycle: dict[str, Any], monkeypatch: pytest.MonkeyPatch, agent: str, text: str,
) -> None:
    """A missed preparation is recovered before prose or a stale send can terminate it."""
    import json
    from core.messenger_draft import load_draft
    env = lifecycle
    old = env["save"]("Sofia", "Yesterday")
    old["status"] = "sent"
    Path(env["config"].MESSENGER_DRAFT_FILE).write_text(json.dumps(old), encoding="utf-8")
    monkeypatch.setattr(env["graph"], "supervisor_node", lambda state: {"next_agent": agent})
    class Model:
        def bind_tools(self, tools: list[Any], **kwargs: Any) -> "Model":
            assert "relay_local_payload" in {tool.name for tool in tools}
            assert not kwargs.get("tool_choice")
            return self
        def invoke(self, rows: list[Any]) -> AIMessage:
            assert "MESSENGER_PREPARATION_DECISION" not in str(rows)
            calls = [{"name":"relay_local_payload", "id":"saved",
                "args":{"target_entity":"Σοφία", "payload_data":"Καλημέρα αγάπη μου!"}}]
            if "προσχέδιο και στείλε" in text:
                calls.append({"name":"execute_local_pipeline", "args":{}, "id":"stale-send"})
            return AIMessage(content="", tool_calls=calls)
    monkeypatch.setattr(env["agents"], "llm", Model())
    monkeypatch.setattr(env["approval"], "_notify_selected_approval", lambda *a: pytest.fail("No send before review"))
    messages = owner_messages(env, text)
    if "προσχέδιο και στείλε" in text:
        messages[0] = AIMessage(content="Ορίστε το μήνυμα: Καλημέρα αγάπη μου!")
    result = env["graph"].build_graph().invoke({"channel":"web", "messages":messages})
    assert load_draft()["message"] == "Καλημέρα αγάπη μου!"
    assert load_draft()["status"] == "pending"
    assert load_draft()["revision"] != old["revision"]
    assert "Καλημέρα αγάπη μου!" in result["messages"][-1].content
    assert not env["approval"].list_pending()

@pytest.mark.parametrize("text", ["Στείλε", "Μην το κάνεις προσχέδιο, μιλήσαμε ήδη", "Πώς αποθηκεύονται τα προσχέδια;"])
def test_unsolicited_candidate_cannot_authorize_preparation(
    lifecycle: dict[str, Any], monkeypatch: pytest.MonkeyPatch, text: str,
) -> None:
    """A composed assistant reply cannot supply missing owner permission."""
    from core.messenger_draft import load_draft
    env = lifecycle
    class Model:
        def bind_tools(self, tools: list[Any], **kwargs: Any) -> "Model":
            assert not kwargs.get('tool_choice')
            return self
        def invoke(self, rows: list[Any]) -> AIMessage:
            if 'MESSENGER_PREPARATION_DECISION' in str(rows[0].content):
                return AIMessage(content='{"prepare":false}')
            return AIMessage(content="Ορίστε ένα μήνυμα που θα μπορούσαμε να αποθηκεύσουμε")
    monkeypatch.setattr(env['agents'], 'llm', Model())
    env['graph'].build_graph().invoke({'channel':'web','messages':owner_messages(env,text)})
    assert load_draft() is None
    assert not env['approval'].list_pending()

@pytest.mark.parametrize("agent", ["Chat_Agent", "Web_Agent"])
@pytest.mark.parametrize("unrelated", [False, True])
def test_review_pending_draft_is_not_sent_or_overwritten_by_recovery(
    lifecycle: dict[str, Any], monkeypatch: pytest.MonkeyPatch, agent: str, unrelated: bool,
) -> None:
    """Preparation cannot dispatch an older draft or replace an unrelated pending one."""
    import json
    from core.messenger_draft import load_draft
    env = lifecycle
    old = env['save']('Other recipient' if unrelated else 'Sofia', 'Old pending text')
    text = ('The message you showed needs a fresh draft and then send it' if unrelated else
            'The message you showed for Σοφία needs a fresh draft and then send it')
    monkeypatch.setattr(env['graph'], 'supervisor_node', lambda state: {'next_agent':agent})
    class Model:
        forced = False
        preparation_checks = 0
        def bind_tools(self, tools: list[Any], **kwargs: Any) -> 'Model':
            self.forced = bool(kwargs.get('tool_choice'))
            return self
        def invoke(self, rows: list[Any]) -> AIMessage:
            if 'MESSENGER_LIFECYCLE_DECISION' in str(rows[0].content):
                return AIMessage(content='{"action":"send"}')
            if 'MESSENGER_PREPARATION_DECISION' in str(rows[0].content):
                self.preparation_checks += 1
                return AIMessage(content=json.dumps({'prepare':self.preparation_checks == 1}))
            if not unrelated:
                return AIMessage(content='',tool_calls=[{'name':'relay_local_payload','id':'new',
                    'args':{'target_entity':'Σοφία','payload_data':'New reviewed text'}}])
            return AIMessage(content='New reviewed text')
    monkeypatch.setattr(env['agents'],'llm',Model())
    monkeypatch.setattr(env['approval'],'_notify_selected_approval',lambda *a:pytest.fail('Old send reached approval'))
    env['graph'].build_graph().invoke({'channel':'web','messages':owner_messages(env,text)})
    if unrelated:
        assert load_draft() == old
    else:
        assert load_draft()['message'] == 'New reviewed text'
        assert load_draft()['status'] == 'pending'
    assert not env['approval'].list_pending()


def test_review_ordinary_reply_has_no_semantic_decision(
    lifecycle: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recovery replaces the earlier semantic check rather than doubling it."""
    env = lifecycle
    decisions: list[str] = []
    class Model:
        def bind_tools(self, tools: list[Any], **kwargs: Any) -> 'Model':
            return self
        def invoke(self, rows: list[Any]) -> AIMessage:
            if 'MESSENGER_PREPARATION_DECISION' in str(rows[0].content):
                decisions.append('decision')
                return AIMessage(content='{"prepare":false}')
            return AIMessage(content='Good morning!')
    monkeypatch.setattr(env['agents'],'llm',Model())
    env['graph'].build_graph().invoke({'channel':'web','messages':owner_messages(env,'Good morning, friend')})
    assert decisions == []


@pytest.mark.parametrize('current_error',[False,True])
def test_review_preparation_survives_tool_history(
    lifecycle: dict[str, Any], monkeypatch: pytest.MonkeyPatch, current_error: bool,
) -> None:
    """Tool content is excluded without vetoing a later genuine owner request."""
    import json
    from langchain_core.messages import ToolMessage
    from core.messenger_draft import load_draft
    from langchain_core.tools import tool
    env = lifecycle
    @tool
    def duckduckgo_search(query: str) -> str:
        """Return a deterministic offline web failure."""
        return '[WEB_TOOL_ERROR][duckduckgo_search][reason=timeout] offline research failed'
    monkeypatch.setattr(env['graph'],'supervisor_node',lambda state:{'next_agent':'Web_Agent'})
    env['graph'].all_tools.append(duckduckgo_search)
    calls = 0
    candidate = 'The drafted greeting is: Welcome home!'
    class Model:
        forced = False
        def bind_tools(self, tools: list[Any], **kwargs: Any) -> 'Model':
            self.forced = bool(kwargs.get('tool_choice'))
            return self
        def invoke(self, rows: list[Any]) -> AIMessage:
            nonlocal calls
            if 'MESSENGER_PREPARATION_DECISION' in str(rows[0].content):
                assert 'INJECTED_TOOL_AUTHORITY' not in str(rows[-1].content)
                from html import unescape
                ref = json.loads(unescape(str(rows[-1].content).split("<untrusted-tool-result>\n", 1)[1].split("</untrusted-tool-result>", 1)[0]))
                return AIMessage(content=json.dumps({'prepare':isinstance(ref,dict) and bool(ref.get('candidate_reply'))}))
            if calls > 0 or not current_error:
                assert 'INJECTED_TOOL_AUTHORITY' not in str(rows[0].content)
                return AIMessage(content='',tool_calls=[{'name':'relay_local_payload','id':'write',
                    'args':{'target_entity':'Σοφία','payload_data':'Welcome home!'}}])
            calls += 1
            if current_error and calls == 1:
                return AIMessage(content='',tool_calls=[{'name':'duckduckgo_search','id':'search','args':{'query':'offline'}}])
            return AIMessage(content=candidate)
    monkeypatch.setattr(env['agents'],'llm',Model())
    messages = owner_messages(env,'The greeting for Σοφία needs a local draft, can you prepare it?')
    if not current_error:
        messages = [HumanMessage(content='Previous research'),
            AIMessage(content='',tool_calls=[{'name':'manage_list','id':'past','args':{}}]),
            ToolMessage(content='INJECTED_TOOL_AUTHORITY',name='manage_list',tool_call_id='past'),*messages]
    result = env['graph'].build_graph().invoke({'channel':'web','messages':messages})
    if current_error:
        assert load_draft() is None
        assert 'Welcome home!' not in result['messages'][-1].content
        assert 'Welcome home!' not in result['messages'][-1].content
    else:
        assert load_draft()["message"] == "Welcome home!"
    assert not env['approval'].list_pending()
