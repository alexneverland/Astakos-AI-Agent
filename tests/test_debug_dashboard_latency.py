"""Browser-facing regression coverage for execution latency rendering."""

import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from memory.execution_trace import ExecutionTrace

NODE_BINARY = shutil.which("node")


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
