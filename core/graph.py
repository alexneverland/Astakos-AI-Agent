# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from core.utils import AgentState  # Το παίρνει έτοιμο, δεν το ξαναγράφουμε!
from tools.system import all_tools
from core.agents import (
    supervisor_node, chat_agent_node, home_agent_node, web_agent_node,
    tech_agent_node, git_agent_node, mail_agent_node, dev_agent_node, tool_router
)
from core.approval import approval_check_node
from core.planner import planner_node, task_executor_node, capture_result_node, pre_check_node, cancel_plan_node, validate_step_node
from core.tool_loop_guard import inspect_tool_loop

# [MASTRO-FIX]: Προσθήκη της λίστας με τους agents για να δουλέψει το routing
AGENT_MAP = [
    "Chat_Agent", "Home_Agent", "Web_Agent", 
    "Tech_Agent", "Git_Agent", "Mail_Agent", "Dev_Agent"
]



# ────────────────────────────────────────────────────────────────
# GRAPH BUILD
# ────────────────────────────────────────────────────────────────

def build_graph():
    workflow = StateGraph(AgentState)

    # Nodes
    workflow.add_node("pre_check",    pre_check_node)
    workflow.add_node("cancel_plan",  cancel_plan_node)
    workflow.add_node("supervisor",   supervisor_node)
    workflow.add_node("Chat_Agent",   chat_agent_node)
    workflow.add_node("Home_Agent",   home_agent_node)
    workflow.add_node("Web_Agent",    web_agent_node)
    workflow.add_node("Tech_Agent",   tech_agent_node)
    workflow.add_node("Git_Agent",    git_agent_node)
    workflow.add_node("Mail_Agent",   mail_agent_node)
    workflow.add_node("Dev_Agent",    dev_agent_node)
    workflow.add_node("tools",          ToolNode(all_tools, handle_tool_errors=True))
    workflow.add_node("approval_check", approval_check_node)
    workflow.add_node("tool_loop_block", tool_loop_block_node)
    workflow.add_node("planner",        planner_node)
    workflow.add_node("task_executor",  task_executor_node)
    workflow.add_node("validate_step",  validate_step_node)
    workflow.add_node("capture_result", capture_result_node)

    # Entry → pre_check (ελέγχει pending plan πριν τον supervisor)
    workflow.set_entry_point("pre_check")

    # pre_check → supervisor | task_executor | cancel_plan
    workflow.add_conditional_edges(
        "pre_check",
        _route_pre_check,
        {"supervisor": "supervisor", "task_executor": "task_executor", "cancel_plan": "cancel_plan"}
    )

    workflow.add_edge("cancel_plan", END)

    # Supervisor → Agents ή Planner
    workflow.add_conditional_edges(
        "supervisor",
        _route_supervisor,
        {**{name: name for name in AGENT_MAP}, "planner": "planner"}
    )

    # Planner → END (περιμένει επιβεβαίωση — ο pre_check_node χειρίζεται το επόμενο turn)
    workflow.add_edge("planner", END)

    # TaskExecutor → Agents (routing με Supervisor logic)
    workflow.add_conditional_edges(
        "task_executor",
        lambda state: state.get("next_agent", "Dev_Agent"),
        {name: name for name in AGENT_MAP}
    )

    # Κάθε agent: αν έχει tool_calls → approval_check, αλλιώς → capture_result ή END
    for agent_name in AGENT_MAP:
        workflow.add_conditional_edges(
            agent_name,
            _should_use_tools,
            {"tools": "approval_check", "tool_loop_block": "tool_loop_block", "validate_step": "validate_step", END: END}
        )

    # approval_check → tools (ok) ή → END (pending/blocked)
    workflow.add_conditional_edges(
        "approval_check",
        lambda state: state.get("approval_status", "ok"),
        {"ok": "tools", "pending": END, "blocked": END}
    )

    workflow.add_edge("tool_loop_block", END)

    # Μετά από tools → επιστροφή στον σωστό agent
    workflow.add_conditional_edges(
        "tools",
        tool_router,
        {name: name for name in AGENT_MAP}
    )

    # validate_step → capture_result (πάντα, ανεξάρτητα από αποτέλεσμα)
    workflow.add_edge("validate_step", "capture_result")

    # capture_result → task_executor (αν υπάρχουν άλλα) ή END
    workflow.add_conditional_edges(
        "capture_result",
        lambda state: "task_executor" if state.get("plan_active") else END,
        {"task_executor": "task_executor", END: END}
    )

    return workflow.compile(checkpointer=None)


def _route_pre_check(state: AgentState) -> str:
    """Routing μετά τον pre_check_node."""
    next_a = state.get("next_agent", "")
    if next_a == "__plan_confirmed__":
        return "task_executor"
    if next_a == "__plan_cancelled__":
        return "cancel_plan"
    return "supervisor"


def _should_use_tools(state: AgentState):
    """Αν tool_calls → tools. Αν plan active → capture. Αλλιώς → END."""
    last_msg = state["messages"][-1]
    tool_calls = getattr(last_msg, "tool_calls", None)
    if tool_calls and len(tool_calls) > 0:
        allowed, reason = inspect_tool_loop(state.get("messages", []))
        if not allowed:
            print(f"\033[91m[Tool Loop Guard]: {reason}\033[0m")
            return "tool_loop_block"
        return "tools"
    if state.get("plan_active") and state.get("plan_index", 0) < len(state.get("plan_tasks", [])):
        return "validate_step"
    return END


def tool_loop_block_node(state: AgentState):
    """Stops repeated tool loops with a visible answer instead of recursion errors."""
    from langchain_core.messages import AIMessage

    _, reason = inspect_tool_loop(state.get("messages", []))
    text = (
        "Σταματάω εδώ γιατί ανίχνευσα επαναλαμβανόμενες κλήσεις εργαλείων "
        f"({reason or 'tool loop guard'}). "
        "Δεν εκτελώ άλλες εντολές. Θέλει έλεγχο του τελευταίου tool/result πριν συνεχίσω."
    )
    return {"messages": [AIMessage(content=text)]}


def _route_supervisor(state: AgentState) -> str:
    """
    Routing από supervisor.
    1. Explicit /plan command → planner
    2. Auto-plan LLM judge → planner αν εντοπίσει multi-step intent
    3. Κανονικός agent αλλιώς
    """
    import re as _re
    from core.utils import clean_message

    last_msg = clean_message(state["messages"][-1].content)

    # ── 1. Explicit /plan ────────────────────────────────────────
    if _re.search(r'(?:^|\])\s*/plan', last_msg.strip()):
        return "planner"

    # ── 2. Auto-plan judge ───────────────────────────────────────
    # Αφαιρούμε timestamp [HH:MM] πριν το evaluation
    clean = _re.sub(r'^\[\d{1,2}:\d{2}\]\s*', '', last_msg).strip()
    try:
        from core.plan_judge import should_auto_plan
        if should_auto_plan(clean):
            print(f"\033[95m[Supervisor]: Auto-plan → planner\033[0m")
            return "planner"
    except Exception as e:
        print(f"\033[90m[Supervisor]: PlanJudge error, skipping: {e}\033[0m")

    # ── 3. Κανονικός agent ───────────────────────────────────────
    return state.get("next_agent", "Chat_Agent")


# Singleton graph — import από παντού
graph = build_graph()
