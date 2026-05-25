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
    workflow.add_node("tools", ToolNode(all_tools, handle_tool_errors=True))

    # Entry
    workflow.set_entry_point("supervisor")

    # Supervisor → Agents
    workflow.add_conditional_edges(
        "supervisor",
        lambda state: state["next_agent"],
        {name: name for name in AGENT_MAP}
    )

    # Κάθε agent: αν έχει tool_calls → tools, αλλιώς → END
    for agent_name in AGENT_MAP:
        workflow.add_conditional_edges(
            agent_name,
            _should_use_tools,
            {"tools": "tools", END: END}
        )

    # Μετά από tools → επιστροφή στον σωστό agent
    workflow.add_conditional_edges(
        "tools",
        tool_router,
        {name: name for name in AGENT_MAP}
    )

    return workflow.compile(checkpointer=None)


def _should_use_tools(state: AgentState):
    """Αν το τελευταίο μήνυμα έχει tool_calls, πάμε στο tools node."""
    last_msg = state["messages"][-1]
    tool_calls = getattr(last_msg, "tool_calls", None)
    if tool_calls and len(tool_calls) > 0:
        return "tools"
    return END


# Singleton graph — import από παντού
graph = build_graph()