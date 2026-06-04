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
from core.planner import planner_node, task_executor_node, capture_result_node

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
    workflow.add_node("planner",        planner_node)
    workflow.add_node("task_executor",  task_executor_node)
    workflow.add_node("capture_result", capture_result_node)

    # Entry
    workflow.set_entry_point("supervisor")

    # Supervisor → Agents ή Planner
    workflow.add_conditional_edges(
        "supervisor",
        _route_supervisor,
        {**{name: name for name in AGENT_MAP}, "planner": "planner"}
    )

    # Planner → TaskExecutor
    workflow.add_edge("planner", "task_executor")

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
            {"tools": "approval_check", "capture": "capture_result", END: END}
        )

    # approval_check → tools (ok) ή → END (pending/blocked)
    workflow.add_conditional_edges(
        "approval_check",
        lambda state: state.get("approval_status", "ok"),
        {"ok": "tools", "pending": END, "blocked": END}
    )

    # Μετά από tools → επιστροφή στον σωστό agent
    workflow.add_conditional_edges(
        "tools",
        tool_router,
        {name: name for name in AGENT_MAP}
    )

    # capture_result → task_executor (αν υπάρχουν άλλα) ή END
    workflow.add_conditional_edges(
        "capture_result",
        lambda state: "task_executor" if state.get("plan_active") else END,
        {"task_executor": "task_executor", END: END}
    )

    return workflow.compile(checkpointer=None)


def _should_use_tools(state: AgentState):
    """Αν tool_calls → tools. Αν plan active → capture. Αλλιώς → END."""
    last_msg = state["messages"][-1]
    tool_calls = getattr(last_msg, "tool_calls", None)
    if tool_calls and len(tool_calls) > 0:
        return "tools"
    if state.get("plan_active") and state.get("plan_index", 0) < len(state.get("plan_tasks", [])):
        return "capture"
    return END


def _route_supervisor(state: AgentState) -> str:
    """Αν το μήνυμα περιέχει /plan → planner. Αλλιώς → κανονικός agent."""
    import re as _re
    from core.utils import clean_message
    last_msg = clean_message(state["messages"][-1].content)
    if _re.search(r'(?:^|\])\s*/plan', last_msg.strip()):
        return "planner"
    return state.get("next_agent", "Chat_Agent")


# Singleton graph — import από παντού
graph = build_graph()
