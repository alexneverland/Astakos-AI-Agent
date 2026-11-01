"""Keep the terminal entry point on the same live-context path as other channels."""

import ast
from pathlib import Path


def test_terminal_queues_semantic_context_extraction_for_both_reply_paths() -> None:
    """External-derived replies must pass only trusted user text to extraction."""
    source = Path(__file__).resolve().parents[1] / "main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    decision = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "external_content_sources"
    )

    for branch in (decision.body, decision.orelse):
        calls = [
            node.value for node in branch
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "enqueue_task"
        ]
        assert any(
            isinstance(call.args[0], ast.Name)
            and call.args[0].id == "extract_and_update_context_flags"
            and isinstance(call.args[1], ast.Name)
            and call.args[1].id == "inp"
            and isinstance(call.args[2], ast.Constant)
            and call.args[2].value == ""
            and isinstance(call.args[3], ast.Constant)
            and call.args[3].value == "terminal"
            for call in calls
        )
