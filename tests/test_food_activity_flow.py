"""Regression coverage for automatic local meal history."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage


class _NamedTool:
    """Minimal tool-shaped object for binding-policy tests."""

    def __init__(self, name: str) -> None:
        self.name = name


def test_meal_report_exposes_only_the_local_history_tool() -> None:
    """A meal report records history but does not request a recipe."""
    from core.agents import _food_tools_for_latest_user_text

    tools = [_NamedTool("recipe_expert"), _NamedTool("log_meal"), _NamedTool("search_memory")]

    selected = _food_tools_for_latest_user_text(
        tools,
        "Borano φάγαμε κιόλας, αυτό με το λιωμένο τυρί.",
    )

    assert [tool.name for tool in selected] == ["log_meal", "search_memory"]


def test_reported_pasta_meal_exposes_the_log_tool_before_approval() -> None:
    """The reported production wording reaches the meal-log capability gate."""
    from core.agents import _food_tools_for_latest_user_text

    tools = [_NamedTool("recipe_expert"), _NamedTool("log_meal"), _NamedTool("search_memory")]
    selected = _food_tools_for_latest_user_text(
        tools,
        (
            "Δεν έκαναμε φασολάκια. Έκανα μακαρόνια με σάλτσα λουκάνικα "
            "και λίγο στήθος κοτόπουλο που είχε μείνει από χθες και φάγαμε όλοι."
        ),
    )

    assert [tool.name for tool in selected] == ["log_meal", "search_memory"]


def test_recipe_request_exposes_recipe_tool_but_not_meal_logging() -> None:
    """A request for ideas may generate recipes without recording a meal."""
    from core.agents import _food_tools_for_latest_user_text

    tools = [_NamedTool("recipe_expert"), _NamedTool("log_meal"), _NamedTool("search_memory")]

    selected = _food_tools_for_latest_user_text(
        tools,
        "Πες καμιά ιδέα για φαγητό για αύριο.",
    )

    assert [tool.name for tool in selected] == ["recipe_expert", "search_memory"]


def test_supported_recipe_words_keep_recipe_tool_available() -> None:
    """Existing registry terms such as menu and recipe remain usable."""
    from core.agents import _food_tools_for_latest_user_text

    tools = [_NamedTool("recipe_expert"), _NamedTool("log_meal")]

    assert [tool.name for tool in _food_tools_for_latest_user_text(tools, "Θέλω μενού.")] == [
        "recipe_expert",
    ]
    assert [tool.name for tool in _food_tools_for_latest_user_text(tools, "recipe") ] == [
        "recipe_expert",
    ]


def test_combined_meal_report_and_recipe_request_exposes_both_food_tools() -> None:
    """One message may both update history and ask how to make the meal."""
    from core.agents import _food_tools_for_latest_user_text

    tools = [_NamedTool("recipe_expert"), _NamedTool("log_meal")]

    selected = _food_tools_for_latest_user_text(
        tools,
        "Έφαγα carbonara και θέλω τη συνταγή.",
    )

    assert [tool.name for tool in selected] == ["recipe_expert", "log_meal"]


def test_greek_question_mark_does_not_turn_a_question_into_a_meal_report() -> None:
    """Greek semicolon punctuation must not activate automatic meal logging."""
    from services.food_intent import is_meal_report

    assert is_meal_report("Τι φάγαμε;") is False


def test_direct_meal_report_skips_stale_external_approval(monkeypatch) -> None:
    """A grounded meal report remains automatic despite old web context."""
    from core.approval import approval_check_node
    from core.untrusted_content import external_content_history_metadata

    save_pending_calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "core.approval.save_pending",
        lambda *args, **_kwargs: save_pending_calls.append(args),
    )
    monkeypatch.setattr("core.approval._notify_telegram", lambda _tool_call: None)
    state = {
        "messages": [
            AIMessage(
                content="A previous web response.",
                additional_kwargs=external_content_history_metadata(["get_news"]),
            ),
            HumanMessage(content="Borano φάγαμε κιόλας, αυτό με το λιωμένο τυρί."),
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "log_meal",
                    "args": {"meal_name": "Borano"},
                    "id": "meal-report",
                }],
            ),
        ],
    }

    assert approval_check_node(state)["approval_status"] == "ok"
    assert save_pending_calls == []


def test_provenance_marked_meal_report_still_requires_approval(monkeypatch) -> None:
    """An uploaded or external meal claim cannot use the direct-user exception."""
    from core.approval import approval_check_node
    from core.untrusted_content import external_content_history_metadata

    save_pending_calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "core.approval.save_pending",
        lambda *args, **_kwargs: save_pending_calls.append(args),
    )
    monkeypatch.setattr("core.approval._notify_telegram", lambda _tool_call: None)
    state = {
        "messages": [
            HumanMessage(
                content="Borano φάγαμε κιόλας, αυτό με το λιωμένο τυρί.",
                additional_kwargs=external_content_history_metadata(["browse_url"]),
            ),
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "log_meal",
                    "args": {"meal_name": "Borano"},
                    "id": "untrusted-meal-report",
                }],
            ),
        ],
    }

    assert approval_check_node(state)["approval_status"] == "pending"
    assert save_pending_calls[0][0] == "log_meal"


def test_recipe_tool_returns_only_recipe_text(monkeypatch) -> None:
    """Internal tool-control text must never reach the conversation."""
    from astakos_skills import recipe_expert

    class _Response:
        content = "Συνταγή Borano"

    monkeypatch.setattr(type(recipe_expert.llm), "invoke", lambda *_args, **_kwargs: _Response())

    result = recipe_expert.recipe_expert.func(
        query="Πες μου τη συνταγή για Borano",
        user_context="",
    )

    assert result == "Συνταγή Borano"
    assert "SYSTEM_INSTRUCTION" not in result
