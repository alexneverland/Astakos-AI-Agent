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


@pytest.mark.parametrize("fail", [False, True])
def test_matrix_terminal_shows_correlated_execution_without_credentials(tmp_path, capsys, fail):
    """Actual Matrix turn output explains calls, results and failed pending calls."""
    from services.matrix_turn import MatrixTurnService
    service = MatrixTurnService(graph=TracedGraph(fail),
        conversation_db_path=str(tmp_path / "history.db"), select_tool_channel=lambda _: None)
    if fail:
        with pytest.raises(RuntimeError):
            service._run_sync("Διάβασε το στίγμα", "$console-turn")
    else:
        service._run_sync("Διάβασε το στίγμα", "$console-turn")
    output = capsys.readouterr().out
    rows = [json.loads(line.partition("[MatrixTrace]: ")[2])
        for line in output.splitlines() if line.startswith("[MatrixTrace]: ")]
    assert rows, "Matrix terminal currently omits its execution evidence"
    assert all(row["correlation_id"] == "$console-turn" for row in rows)
    assert len({row["trace_id"] for row in rows}) == 1
    assert rows[0]["event"] == "turn_started"
    assert rows[-1]["event"] == "turn_finished"
    assert any(row["event"] == "graph_step" and row["node"] == "Home_Agent" for row in rows)
    assert any(row["event"] == "tool_called" and row["tool"] == "get_current_location" for row in rows)
    assert "private-test-token" not in output
    assert "private-result-key" not in output
    if fail:
        assert any(row["event"] == "tool_unresolved" for row in rows)
        assert rows[-1]["error"] == "RuntimeError"
    else:
        assert any(row["event"] == "tool_result" and "40.6449" in row["result"] for row in rows)
        assert rows[-1]["response"] == "Βλέπω το στίγμα σου."


def test_intercept_terminal_explains_no_graph_run(tmp_path, capsys):
    """A local command must not look like a graph or tool execution."""
    from services.matrix_turn import MatrixTurnService
    service = MatrixTurnService(graph=TracedGraph(),
        conversation_db_path=str(tmp_path / "history.db"), command_handler=lambda _: "ready")
    service._run_sync("/status", "$intercept-console")
    rows = [json.loads(line.partition("[MatrixTrace]: ")[2])
        for line in capsys.readouterr().out.splitlines() if line.startswith("[MatrixTrace]: ")]
    assert rows
    assert any(row["event"] == "phase" and row["phase"] == "graph_used" and row["value"] == 0 for row in rows)
    assert not any(row["event"] in {"graph_step", "tool_called"} for row in rows)


def test_terminal_previews_are_bounded_redacted_and_single_line(capsys):
    """Credentials and multiline tool data remain safe in the new sink."""
    from memory.execution_trace import ExecutionTrace
    trace = ExecutionTrace("matrix", 'private_key="console-secret"',
        console=True, correlation_id="$safe-console")
    trace.process_event({"Home_Agent": {"messages": [AIMessage(content="", tool_calls=[{
        "id": "safe-call", "name": "read_local_file",
        "args": {"password": "console-secret", "text": "x" * 2000}}])]}})
    trace.process_event({"tools": {"messages": [ToolMessage(tool_call_id="safe-call",
        content='-----BEGIN PRIVATE KEY-----\nconsole-secret\n-----END PRIVATE KEY-----\n' + "y" * 2000)]}})
    trace.finalize(response='passphrase="console-secret"\n' + "z" * 2000)
    output = capsys.readouterr().out
    assert "console-secret" not in output
    rows = [json.loads(line.partition("[MatrixTrace]: ")[2]) for line in output.splitlines()]
    assert all(len(row.get(key, "") or "") <= 301 for row in rows
        for key in ("args", "result", "response", "user_message"))
    trace.save()


def test_closed_terminal_does_not_break_matrix_reply_or_saved_trace(tmp_path, monkeypatch):
    """The diagnostic sink must not become a new runtime failure boundary."""
    from services.matrix_turn import MatrixTurnService
    from memory.execution_trace import load_traces
    def closed_terminal(*args, **kwargs):
        raise BrokenPipeError("synthetic closed terminal")
    monkeypatch.setattr("builtins.print", closed_terminal)
    service = MatrixTurnService(graph=TracedGraph(),
        conversation_db_path=str(tmp_path / "history.db"), select_tool_channel=lambda _: None)
    assert service._run_sync("Διάβασε το στίγμα", "$closed-console") == "Βλέπω το στίγμα σου."
    assert load_traces()[0]["response"] == "Βλέπω το στίγμα σου."


def test_closed_text_stream_does_not_interrupt_trace_lifecycle(tmp_path, monkeypatch):
    """A real closed stream raises ValueError rather than BrokenPipeError."""
    import io
    import sys
    from memory.execution_trace import ExecutionTrace, load_traces
    stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    stream.close()
    with monkeypatch.context() as context:
        context.setattr(sys, "stdout", stream)
        trace = ExecutionTrace("web", "offline closed stream")
        trace.mark_phase("graph_used", 0)
        trace.finalize(response="ready")
        trace.save()
    assert load_traces()[0]["response"] == "ready"


@pytest.mark.parametrize("fail", [False, True])
def test_telegram_photo_error_or_empty_response_retains_trace(monkeypatch, capsys, fail):
    """Photo graph errors and empty replies both complete and persist their trace."""
    from clients import telegram_bot as bot
    from memory.execution_trace import load_traces
    monkeypatch.setattr(bot, "_load_shared_context_messages", lambda _: [])
    monkeypatch.setattr("tools.telegram.send_telegram_msg", lambda *args: 1)
    def stream(*args, **kwargs):
        yield {"Home_Agent": {"messages": [AIMessage(content="", tool_calls=[{
            "name": "read_local_file", "id": "photo-pending", "args": {}}])]}}
        if fail:
            raise RuntimeError("offline photo failure")
    monkeypatch.setattr(bot.graph, "stream", stream)
    bot._process_photo_with_question("offline.png", "offline.png", "offline analysis", "offline question", "user123")
    rows = load_traces()
    assert len(rows) == 1
    assert rows[0]["error"] == ("RuntimeError" if fail else "NoResponse")
    assert rows[0]["tool_calls"][0]["status"] == "unresolved"
    logs = [json.loads(line.removeprefix("[TelegramTrace]: "))
        for line in capsys.readouterr().out.splitlines() if line.startswith("[TelegramTrace]: ")]
    assert sum(row["event"] == "turn_finished" for row in logs) == 1


def test_console_output_can_be_disabled_explicitly(capsys):
    """Offline callers may explicitly keep only the stored trace sink."""
    from memory.execution_trace import ExecutionTrace
    trace = ExecutionTrace("web", "safe offline request", console=False)
    trace.process_event({"Home_Agent": {"messages": []}})
    trace.finalize(response="ready")
    trace.save()
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("channel", ["web", "telegram", "matrix"])
@pytest.mark.parametrize("fail", [False, True])
def test_all_channels_log_complete_correlated_tool_lifecycle(channel, fail, capsys):
    """The default recorder sink explains both success and unresolved failures."""
    from memory.execution_trace import ExecutionTrace, load_traces
    trace = ExecutionTrace(channel, 'password="offline-secret"')
    for event in TracedGraph(False).stream({}, {}):
        trace.process_event(event)
        if fail and "Home_Agent" in event:
            break
    trace.finalize(response=None if fail else "ready", error="RuntimeError" if fail else None)
    trace.save()
    prefix = f"[{channel.title()}Trace]: "
    output = capsys.readouterr().out
    rows = [json.loads(line.removeprefix(prefix)) for line in output.splitlines()]
    assert rows
    assert all(row["channel"] == channel and row["correlation_id"] == trace.trace_id for row in rows)
    assert rows[0]["event"] == "turn_started"
    assert rows[-1]["event"] == "turn_finished"
    assert any(row["event"] == "tool_called" for row in rows)
    assert any(row["event"] == ("tool_unresolved" if fail else "tool_result") for row in rows)
    assert rows[-1]["error"] == ("RuntimeError" if fail else None)
    assert not any(secret in output for secret in ("offline-secret", "private-test-token", "private-result-key"))
    assert load_traces()[0]["correlation_id"] == trace.trace_id
