"""Offline reproductions of PR 261 review findings."""
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

@pytest.fixture(autouse=True)
def offline_network(monkeypatch):
    """Permit only loopback socketpair traffic required by Windows asyncio."""
    import socket
    original = socket.socket.connect
    original_ex = socket.socket.connect_ex
    def connect(sock, address):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost"):
            return original(sock, address)
        pytest.fail("External network blocked")
    monkeypatch.setattr(socket.socket, "connect", connect)
    def connect_ex(sock, address):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost"):
            return original_ex(sock, address)
        pytest.fail("External network blocked")
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)


def test_mixed_receipt_preserves_saved_draft():
    """A sibling tool result cannot hide the native saved draft."""
    from services.messenger_lifecycle import messenger_lifecycle_boundary
    from core.i18n import t
    text = t("prompts.ext_draft_2") + "\nMessage: Saved text"
    history = [ToolMessage(content=text, name="relay_local_payload", tool_call_id="draft"),
               ToolMessage(content="Goal updated", name="update_goal_milestones_tool", tool_call_id="goal")]
    _, result = messenger_lifecycle_boundary({}, history, "Chat_Agent", lambda _: pytest.fail("No synthesis"))
    assert result and "Saved text" in result["messages"][-1].content
    assert "Goal updated" in result["messages"][-1].content


def test_non_draft_call_does_not_satisfy_preparation():
    """A sibling action must finish, while preparation still cannot claim success."""
    from services.messenger_lifecycle import require_draft_tool_result
    class Model:
        def bind_tools(self, *a, **k):
            return self
        def invoke(self, rows):
            return AIMessage(content="", tool_calls=[{"name":"relay_local_payload", "args":{}, "id":"draft"}])
    response = AIMessage(content="saved", tool_calls=[{"name":"update_goal_milestones_tool", "args":{}, "id":"goal"}])
    result = require_draft_tool_result(response, "explicit_create", [], Model())
    assert {call["name"] for call in result.tool_calls} == {"relay_local_payload", "update_goal_milestones_tool"}


def test_invalid_guard_cannot_silently_skip_pending_lifecycle(monkeypatch):
    """A failed history read gives a visible unavailable outcome for pending work."""
    from services.messenger_lifecycle import messenger_lifecycle_boundary
    monkeypatch.setattr("core.messenger_draft.active_draft_status", lambda: (True, "active", {"message":"Hello"}))
    _, result = messenger_lifecycle_boundary({"messenger_draft_write_guard":{"valid":False}},
        [HumanMessage(content="Send it")], "Chat_Agent", lambda _: pytest.fail("Invalid guard"))
    assert result and result["messages"][-1].content


def test_send_claim_rejects_replacement_and_replay(tmp_path, monkeypatch):
    """Native dispatch claims are revision bound and cannot replay uncertain sends."""
    import config
    from core import messenger_draft as draft
    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(tmp_path / "draft.json"))
    first = draft.save_draft("Sofia", "First")
    newer = draft.save_draft("Sofia", "Newer")
    with pytest.raises(ValueError):
        draft.claim_draft_send(first["revision"])
    assert draft.load_draft() == newer
    claimed = draft.claim_draft_send(newer["revision"])
    assert claimed["status"] == "sending"
    with pytest.raises(ValueError):
        draft.claim_draft_send(newer["revision"])
    replacement = draft.save_draft("Sofia", "Replacement during send")
    draft.finish_draft_send(newer["revision"], succeeded=True)
    assert draft.load_draft() == replacement


@pytest.mark.asyncio
async def test_matrix_feedback_receipt_keeps_owner_last(tmp_path, monkeypatch):
    """Run the real Matrix turn service, including its dated no-action receipt."""
    from services.matrix_turn import MatrixTurnService
    from services.routine_context_clarification import QuestionAnswer
    monkeypatch.setattr("services.routine_context_clarification.try_context_question_reply", lambda *a, **k: QuestionAnswer())
    monkeypatch.setattr("core.messenger_draft.active_draft_status", lambda: (False, "missing", None))
    class Graph:
        def stream(self, state, config):
            assert isinstance(state["messages"][-1], HumanMessage)
            assert any(isinstance(row, SystemMessage) for row in state["messages"])
            yield {"Chat_Agent":{"messages":[AIMessage(content="Okay")]}}
    service = MatrixTurnService(graph=Graph(), conversation_db_path=str(tmp_path / "history.db"),
        persisted_routine_confirmation_handler=lambda *a, **k: SystemMessage(content="[ROUTINE_FEEDBACK_NO_ACTION]"))
    await service("Δεν χρειάζεται πια το χθεσινό μήνυμα, μιλήσαμε", "$owner")


def test_approval_binds_revision_before_replacement(tmp_path, monkeypatch):
    """Even a delayed approval cannot adopt a newer shared draft."""
    import config
    from core import approval, messenger_draft
    from tools.web import execute_local_pipeline
    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(tmp_path / "draft.json"))
    monkeypatch.setattr(approval, "PENDING_FILE", str(tmp_path / "pending.json"))
    original = messenger_draft.save_draft("Sofia", "Approved message")
    approval.save_pending("execute_local_pipeline", {}, "send", channel="matrix")
    assert approval.get_pending("send")["tool_args"]["expected_draft_revision"] == original["revision"]
    newer = messenger_draft.save_draft("Sofia", "Replacement")
    result = approval.execute_approved_pending("send", [execute_local_pipeline])
    assert "Replacement" not in str(result)
    assert messenger_draft.load_draft() == newer


def test_duplicate_approvals_execute_once(tmp_path, monkeypatch):
    """Atomic pending claims prevent duplicate approvals before transport work."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from core import approval
    monkeypatch.setattr(approval, "PENDING_FILE", str(tmp_path / "pending.json"))
    monkeypatch.setattr("core.messenger_draft.load_draft", lambda: {"revision":"v1"})
    approval.save_pending("execute_local_pipeline", {}, "send")
    barrier = Barrier(2)
    original = approval.get_pending
    def read(call_id):
        item = original(call_id)
        barrier.wait(timeout=10)
        return item
    monkeypatch.setattr(approval, "get_pending", read)
    calls = []
    class Tool:
        name = "execute_local_pipeline"
        def invoke(self, args):
            calls.append(args)
            return "Sent"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: approval.execute_approved_pending("send", [Tool()]), range(2)))
    assert len(calls) == 1
    assert sum(result["ok"] for result in results) == 1


@pytest.mark.parametrize("replacement", [False, True])
@pytest.mark.parametrize("interrupted", [False, True])
def test_native_send_transport_is_claimed_and_cleanup_preserves_replacement(tmp_path, monkeypatch, replacement, interrupted):
    """Run the real send tool with only Playwright and waits replaced offline."""
    from unittest.mock import MagicMock
    import config
    from core import messenger_draft as draft
    import tools.web as web
    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(tmp_path / "draft.json"))
    monkeypatch.setattr(web, "_load_messenger_contacts", lambda: {})
    saved = draft.save_draft("Sofia", "Approved message")
    browser = MagicMock()
    page = browser.new_page.return_value
    entered = []
    def press(key):
        entered.append(key)
        assert draft.load_draft()["status"] == "sending"
        if replacement:
            draft.save_draft("Sofia", "Newer work")
        if interrupted:
            raise RuntimeError("Transport accepted but result uncertain")
    page.locator.return_value.last.press.side_effect = press
    playwright = MagicMock()
    playwright.return_value.__enter__.return_value.chromium.launch_persistent_context.return_value = browser
    monkeypatch.setattr("playwright.sync_api.sync_playwright", playwright)
    monkeypatch.setattr("time.sleep", lambda _: None)
    web.execute_local_pipeline.invoke({"expected_draft_revision": saved["revision"]})
    current = draft.load_draft()
    if replacement:
        assert current["message"] == "Newer work" and current["status"] == "pending"
    else:
        assert current["status"] == ("uncertain" if interrupted else "sent")
    web.execute_local_pipeline.invoke({"expected_draft_revision": saved["revision"]})
    assert entered == ["Enter"]


def test_retirement_serializes_history_append(tmp_path, monkeypatch):
    """A history writer cannot commit between the guard check and replacement."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    import config
    from core import messenger_draft as draft
    from memory.conversation_history import append_message
    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(tmp_path / "draft.json"))
    first = append_message(role="user", channel="web", content="Retire it", db_path=config.CONVERSATION_DB_FILE)
    draft.save_draft("Sofia", "Old message")
    guard = draft.capture_draft_write_guard([HumanMessage(content="Retire it", additional_kwargs={"astakos_owner_rowid": first["rowid"]})])
    attempting, finished = Event(), Event()
    original = draft._replace_draft
    def append():
        attempting.set()
        append_message(role="user", channel="matrix", content="Newer owner turn", db_path=config.CONVERSATION_DB_FILE)
        finished.set()
    with ThreadPoolExecutor(max_workers=1) as pool:
        futures = []
        def replace(data):
            futures.append(pool.submit(append))
            assert attempting.wait(2)
            assert not finished.wait(0.1)
            original(data)
        monkeypatch.setattr(draft, "_replace_draft", replace)
        assert draft.clear_draft(write_guard=guard)
        futures[0].result(timeout=10)
    assert finished.is_set()


def test_matrix_explicit_clear_cannot_erase_intervening_draft(tmp_path, monkeypatch):
    """The channel shortcut passes the observed revision to native clear."""
    from types import SimpleNamespace
    import config
    from core import messenger_draft as draft
    from services.matrix_turn import MatrixTurnService
    from services.routine_context_clarification import QuestionAnswer
    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(tmp_path / "draft.json"))
    monkeypatch.setattr("services.routine_context_clarification.try_context_question_reply", lambda *a, **k: QuestionAnswer())
    draft.save_draft("Sofia", "Old draft")
    def classify(*args, **kwargs):
        draft.save_draft("Sofia", "Newer draft")
        return SimpleNamespace(intent="clear_draft")
    monkeypatch.setattr("services.messenger_intent.classify_messenger_intent", classify)
    service = MatrixTurnService(graph=object(), conversation_db_path=str(tmp_path / "history.db"))
    service._run_sync("Καθάρισε το προσχέδιο", "$clear")
    assert draft.load_draft()["message"] == "Newer draft"


def test_unbound_legacy_approval_cannot_adopt_current_draft(tmp_path, monkeypatch):
    """Pre-upgrade pending approvals require a new, revision-bound request."""
    from core import approval
    monkeypatch.setattr(approval, "get_pending", lambda _: {
        "status":"pending", "tool_name":"execute_local_pipeline", "tool_args":{}})
    class Tool:
        name = "execute_local_pipeline"
        def invoke(self, args):
            pytest.fail("Unbound send reached transport")
    assert approval.execute_approved_pending("legacy", [Tool()])["status"] == "draft_unbound"

def test_preparation_never_batches_old_send_with_new_write() -> None:
    """Even a provider supplying both tools must finish local preparation first."""
    from services.messenger_lifecycle import require_draft_tool_result
    response = AIMessage(content='', tool_calls=[
        {'name':'execute_local_pipeline','id':'old-send','args':{}},
        {'name':'relay_local_payload','id':'new-write','args':{}},
    ])
    result = require_draft_tool_result(response, 'response_grounded_preparation', [], None)
    assert [call['name'] for call in result.tool_calls] == ['relay_local_payload']

@pytest.mark.parametrize('kind',['tool_use','function_call'])
def test_review_send_removed_from_native_content(kind: str) -> None:
    """Normalization cannot retain a native send hidden beside the surviving write."""
    from services.messenger_lifecycle import require_draft_tool_result
    response = AIMessage(content=[{'type':'text','text':'Prepared'},
        {'type':kind,'name':'execute_local_pipeline','id':'old','input':{}}],tool_calls=[
        {'name':'execute_local_pipeline','args':{},'id':'old'},
        {'name':'relay_local_payload','args':{},'id':'new'}])
    result = require_draft_tool_result(response,'response_grounded_preparation',[],None)
    assert 'execute_local_pipeline' not in str(result.content)
    assert 'Prepared' in str(result.content)
    assert [c['name'] for c in result.tool_calls] == ['relay_local_payload']
