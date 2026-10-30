"""Browser-facing regression coverage for execution latency rendering."""

import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from memory.execution_trace import ExecutionTrace

NODE_BINARY = shutil.which("node")


@pytest.mark.skipif(NODE_BINARY is None, reason="Node.js is required")
def test_latency_panel_displays_pregraph_model_retry_and_named_spans():
    """Render the diagnostic shape that explains a multi-minute project reply."""
    dashboard = (Path(__file__).parents[1] / "api" / "debug_dashboard.html").read_text(encoding="utf-8")
    functions = dashboard[dashboard.index("function latencyColor"):dashboard.index("async function fetchAllNow")]
    row = {"timestamp": "2030-01-15T10:00:00", "channel": "web", "trace_id": "demo1234",
           "duration_ms": 408000, "latency": {"total_ms": 408000, "model_wall_ms": 380000,
           "retry_wait_wall_ms": 2000, "uncovered_ms": 1000, "dropped_spans": 0,
           "spans": [{"name": "model_call", "stage": "routine_feedback", "start_ms": 5,
                      "duration_ms": 180000, "provider": "demo", "model": "demo-model", "error": None}]}}
    script = f"""
const panel = {{innerHTML:''}};
const document = {{getElementById: () => panel}};
const esc = value => String(value);
{functions}
renderLatencyPanel([{json.dumps(row)}]);
process.stdout.write(panel.innerHTML);
"""
    result = subprocess.run([NODE_BINARY, "-"], input=script, text=True, capture_output=True, check=True)
    for expected in ["408.0s", "380.0s", "Retry wait", "Uncovered", "routine_feedback", "demo-model", "180.000s"]:
        assert expected in result.stdout


@pytest.mark.skipif(
    NODE_BINARY is None,
    reason="Node.js is required to execute dashboard JavaScript",
)
def test_latency_panel_renders_total_for_repeated_home_invokes() -> None:
    """The visible LLM metric must include every Home-Agent pass."""
    dashboard = (
        Path(__file__).parents[1] / "api" / "debug_dashboard.html"
    ).read_text(encoding="utf-8")
    functions = dashboard[
        dashboard.index("function latencyColor"):
        dashboard.index("async function fetchAllNow")
    ]
    trace = ExecutionTrace("web", "change the sleep routine time")
    for duration_ms in (145_000, 8_117):
        trace._process_message(
            "Home_Agent",
            SimpleNamespace(
                type="ai",
                tool_calls=[],
                _astakos_phase_timings={"home_invoke_ms": duration_ms},
            ),
        )
    phase_timings = json.dumps(trace.phase_timings)
    script = f"""
const panel = {{ innerHTML: '' }};
const document = {{ getElementById: () => panel }};
const esc = (value) => String(value);
{functions}
renderLatencyPanel([{{
  timestamp: '2026-09-14T22:10:00',
  agent: 'approval_check',
  channel: 'web',
  duration_ms: 158425,
  tool_calls: [],
  phase_timings: {phase_timings}
}}]);
process.stdout.write(panel.innerHTML);
"""

    result = subprocess.run(
        [NODE_BINARY or "node", "-"],
        input=script,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "LLM invoke" in result.stdout
    assert "153.1s" in result.stdout
    assert "8.1s" not in result.stdout
