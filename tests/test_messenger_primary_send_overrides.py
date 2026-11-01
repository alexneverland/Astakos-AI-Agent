"""Primary sends cannot turn stored-revision approval into a direct send."""
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from tests.test_messenger_lifecycle_regression import lifecycle, owner_messages

pytestmark = pytest.mark.usefixtures("offline_behavioral_io")


@pytest.mark.parametrize("overrides", ["both", "recipient", "message"])
@pytest.mark.parametrize("mutation", ["unchanged", "replacement", "retired", "expired"])
def test_primary_override_is_removed_through_native_approval_and_execution(lifecycle, monkeypatch, mutation, overrides):
    """Exercise real graph, pending store and native pipeline with fake browser I/O."""
    from core import messenger_draft
    import tools.web as web

    env = lifecycle
    original = env["save"]("demo-recipient", "Reviewed demo text")
    monkeypatch.setattr(env["approval"], "_notify_selected_approval", lambda *args: "telegram")
    monkeypatch.setattr("core.messaging_channel.resolve_external_channel", lambda: "telegram")
    monkeypatch.setattr(web, "_load_messenger_contacts", lambda: {})
    monkeypatch.setattr(web.execute_local_pipeline, "func", env["native_pipeline"])
    browser = MagicMock()
    page = browser.new_page.return_value
    entered = []
    page.locator.return_value.last.press.side_effect = lambda key: entered.append(key)
    playwright = MagicMock()
    playwright.return_value.__enter__.return_value.chromium.launch_persistent_context.return_value = browser
    monkeypatch.setattr("playwright.sync_api.sync_playwright", playwright)
    monkeypatch.setattr("time.sleep", lambda _: None)

    class Model:
        """Supply overrides despite the stored-draft send tool contract."""
        def bind_tools(self, tools, **kwargs):
            return self

        def invoke(self, rows, **kwargs):
            if "MESSENGER_LIFECYCLE_DECISION" in str(rows[0].content):
                return AIMessage(content='{"action":"none"}')
            args = {"expected_draft_revision":"model-invented-revision"}
            if overrides in {"both", "recipient"}:
                args["target_name"] = "override-recipient"
            if overrides in {"both", "message"}:
                args["message"] = "Unreviewed override text"
            return AIMessage(content="", tool_calls=[{"name":"execute_local_pipeline", "id":"send-override", "args":args}])

    monkeypatch.setattr(env["agents"], "llm", Model())
    env["graph"].build_graph().invoke({"channel":"web", "messages":owner_messages(env, "Send the reviewed draft")})
    pending = env["approval"].list_pending()
    assert len(pending) == 1
    if mutation == "replacement":
        env["save"]("other-recipient", "Replacement must survive")
    elif mutation == "retired":
        assert messenger_draft.clear_draft()
    elif mutation == "expired":
        from datetime import datetime, timedelta

        class Later(datetime):
            """Advance only native draft time, leaving approval time unchanged."""
            @classmethod
            def now(cls, tz=None):
                return datetime.now(tz) + timedelta(days=1)

        monkeypatch.setattr(messenger_draft, "datetime", Later)
    before = messenger_draft.load_draft()
    result = env["approval"].execute_approved_pending(pending[0]["tool_call_id"], [web.execute_local_pipeline])
    if mutation == "unchanged":
        assert entered == ["Enter"]
        page.locator.return_value.last.fill.assert_called_once_with("Reviewed demo text")
        assert page.goto.call_args.args[0] == "https://www.messenger.com/t/demo-recipient"
        assert messenger_draft.load_draft()["status"] == "sent"
    else:
        assert entered == []
        playwright.assert_not_called()
        assert messenger_draft.load_draft() == before
    assert pending[0]["tool_args"] == {"expected_draft_revision":original["revision"]}
    assert "Unreviewed override text" not in str(result)
