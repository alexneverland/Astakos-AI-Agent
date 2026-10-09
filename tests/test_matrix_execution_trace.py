"""Matrix execution evidence survives successful, failed and intercepted turns."""

import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage


@pytest.fixture(autouse=True)
def isolate_matrix_boundaries(tmp_path, monkeypatch):
    from memory import execution_trace
    from services import routine_context_clarification as clarification
    from core import messenger_draft
    monkeypatch.setattr(execution_trace, "_TRACES_DIR", str(tmp_path / "traces"))
    monkeypatch.setattr(clarification, "try_context_question_reply",
        lambda *a, **kw: clarification.QuestionAnswer())
    monkeypatch.setattr(messenger_draft, "active_draft_status", lambda: (False, "none", {}))


class TracedGraph:
    def __init__(self, fail=False):
        self.fail = fail

    def stream(self, state: dict[str, Any], config: dict[str, Any]):
        yield {"supervisor": {"messages": []}}
        yield {"Home_Agent": {"messages": [AIMessage(content="", tool_calls=[{
            "name": "get_current_location", "args": {"token": "private-test-token"}, "id": "gps-1"}])]}}
        if self.fail:
            raise RuntimeError("simulated graph failure")
        yield {"tools": {"messages": [ToolMessage(name="get_current_location", tool_call_id="gps-1",
            content='{"lat":40.6449,"lon":22.9364,"api_key":"private-result-key"}')]}}
        yield {"Home_Agent": {"messages": [AIMessage(content="Βλέπω το στίγμα σου.")]}}


@pytest.mark.parametrize("fail", [False, True])
def test_matrix_persists_tools_response_and_failure(tmp_path, fail):
    from services.matrix_turn import MatrixTurnService
    from memory.execution_trace import load_traces
    service = MatrixTurnService(graph=TracedGraph(fail),
        conversation_db_path=str(tmp_path / "history.db"), select_tool_channel=lambda _: None)
    if fail:
        with pytest.raises(RuntimeError):
            service._run_sync("Τώρα διάβασε στίγμα που είμαι", "$trace-turn")
    else:
        assert service._run_sync("Τώρα διάβασε στίγμα που είμαι", "$trace-turn") == "Βλέπω το στίγμα σου."
    rows = load_traces()
    assert len(rows) == 1
    row = rows[0]
    assert row["channel"] == "matrix"
    assert row["correlation_id"] == "$trace-turn"
    assert row["agent"] == "Home_Agent"
    assert row["tool_calls"][0]["tool"] == "get_current_location"
    assert row["duration_ms"] >= 0
    assert "private-test-token" not in json.dumps(row)
    assert "private-result-key" not in json.dumps(row)
    if fail:
        assert row["error"] == "RuntimeError"
        assert row["tool_calls"][0]["status"] == "unresolved"
    else:
        assert row["response"] == "Βλέπω το στίγμα σου."
        assert '40.6449' in row["tool_calls"][0]["result"]
        assert row["tool_calls"][0]["duration_ms"] >= 0


def test_command_intercept_has_trace_without_claiming_graph_execution(tmp_path):
    from services.matrix_turn import MatrixTurnService
    from memory.execution_trace import load_traces
    service = MatrixTurnService(graph=TracedGraph(),
        conversation_db_path=str(tmp_path / "history.db"), command_handler=lambda _: "status ready")
    assert service._run_sync("/status", "$command-turn") == "status ready"
    row = load_traces()[0]
    assert row["phase_timings"]["graph_used"] == 0
    assert row["tool_calls"] == []
    assert row["response"] == "status ready"


def test_web_and_matrix_processes_preserve_all_trace_records(tmp_path):
    """The shared day file must survive writers in separate runtimes."""
    import subprocess
    import sys
    from memory.execution_trace import load_traces
    source = '''
import sys
from memory import execution_trace as module
module._TRACES_DIR = sys.argv[1]
for index in range(20):
    trace = module.ExecutionTrace(sys.argv[2], "synthetic offline trace")
    trace.finalize(response="ready")
    trace.save()
'''
    processes = [subprocess.Popen([sys.executable, "-c", source, str(tmp_path / "traces"), channel],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for channel in ("web", "matrix")]
    for process in processes:
        output, error = process.communicate(timeout=30)
        assert process.returncode == 0, error
    rows = load_traces(limit=100)
    assert len(rows) == 40
    assert len({row["trace_id"] for row in rows}) == 40
    assert {row["channel"] for row in rows} == {"web", "matrix"}


@pytest.mark.parametrize("content", [
    '[UNTRUSTED TOOL RESULT] API key: private-preview-secret',
    '{"nested":{"passwordHash":"private-preview-secret"}}',
    'Authorization: Bearer private-preview-secret',
    '{"private_key":"private-preview-secret"}',
    '{"nested":{"passphrase":"private-preview-secret"}}',
    '[UNTRUSTED TOOL RESULT] private_key: "private-preview-secret"',
    "pass_phrase='private-preview-secret'",
    'private_key="-----BEGIN PRIVATE KEY-----\nprivate-preview-secret\n-----END PRIVATE KEY-----"',
    '-----BEGIN RSA PRIVATE KEY-----\nprivate-preview-secret\n-----END RSA PRIVATE KEY-----',
    '-----BEGIN PRIVATE KEY-----\nprivate-preview-secret',
    'private key: "private-preview-secret"',
    'passphrase="escaped\\\"private-preview-secret"',
    '[UNTRUSTED TOOL RESULT] {"private_key":"private-preview-secret"}',
])
def test_persisted_tool_previews_redact_credentials_before_truncation(content):
    from memory.execution_trace import ExecutionTrace, load_traces
    trace = ExecutionTrace("matrix", "synthetic safe request")
    trace.process_event({"tools": {"messages": [ToolMessage(name="read_local_file",
        tool_call_id="preview", content=content)]}})
    trace.finalize(response="ready")
    trace.save()
    assert "private-preview-secret" not in json.dumps(load_traces())
    assert "REDACTED" in load_traces()[0]["tool_calls"][0]["result"]


def test_redaction_large_adversarial_input_finishes_within_budget():
    """Use a process deadline so a backtracking regression cannot hang pytest."""
    import subprocess
    import sys
    source = '''
from memory.execution_trace import _truncate
for value in ('-' * 20000, 'x' * 20000, ' ' * 20000):
    assert len(_truncate(value)) == 301
'''
    result = subprocess.run([sys.executable, "-c", source], capture_output=True,
                            text=True, timeout=3)
    assert result.returncode == 0, result.stderr


def test_redaction_preserves_safe_geometry_and_redacts_all_trace_previews():
    """Persist argument, result, user and response previews through the recorder."""
    from memory.execution_trace import ExecutionTrace, load_traces
    trace = ExecutionTrace("matrix", 'passphrase="private-preview-secret"')
    trace.process_event({"Home_Agent": {"messages": [AIMessage(content="", tool_calls=[{
        "id": "keys", "name": "read_local_file",
        "args": {"private_key": "private-preview-secret", "lat": 40.6449}}])]}})
    trace.process_event({"tools": {"messages": [ToolMessage(name="read_local_file",
        tool_call_id="keys", content='{"lat":40.6449,"private_key":"private-preview-secret"}')]}})
    trace.finalize(response="passphrase=private-preview-secret")
    trace.save()
    rows = load_traces()
    assert "private-preview-secret" not in json.dumps(rows)
    assert '40.6449' in rows[0]["tool_calls"][0]["args"]
    assert '40.6449' in rows[0]["tool_calls"][0]["result"]


def test_redaction_retains_public_keys_and_ordinary_text():
    """Nearby non-credential data remains useful diagnostic evidence."""
    from memory.execution_trace import _redact_preview
    value = '{"public_key":"synthetic-public-value","place":"Park","lat":40.6449}'
    assert json.loads(_redact_preview(value)) == json.loads(value)
