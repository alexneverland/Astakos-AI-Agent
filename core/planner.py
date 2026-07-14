# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Planning Agent
# Takes goal → outputs structured task list → executes step-by-step
# ================================================================

from core.i18n import t
import json
import os
import re
from datetime import datetime
from langchain_core.messages import HumanMessage, AIMessage


import config

def _planner_pending_user_key(state) -> str:
    channel = str(state.get("channel") or "unknown").strip().lower()
    user_id = str(state.get("user_id") or state.get("thread_id") or "default").strip()
    return f"{channel}:{user_id}"


# ────────────────────────────────────────────────────────────────
# Planner Node — creates a task list from a goal
# ────────────────────────────────────────────────────────────────

def planner_node(state):
    """
    Takes the goal (message after /plan) and generates a structured task list.
    Saves to state: plan_tasks, plan_index=0, plan_results=[]
    """
    from core.brain import llm_heavy, safe_llm_invoke
    from core.utils import clean_message

    last_msg = clean_message(state["messages"][-1].content)
    # Remove timestamp [HH:MM] and /plan prefix
    goal = re.sub(r'^\[\d{1,2}:\d{2}\]\s*', '', last_msg).strip()
    goal = re.sub(r'^/plan\b\s*', '', goal).strip()

    print(f"\033[95m[Planner]: Analyzing goal: {goal[:80]}\033[0m")

    from core.utils import load_agent_prompt
    base_prompt = load_agent_prompt("planner_main")
    prompt = base_prompt.format(goal=goal)

    try:
        response = safe_llm_invoke(llm_heavy, [HumanMessage(content=prompt)])
        from core.utils import clean_message, extract_json_from_text
        raw = clean_message(response.content)
        tasks = extract_json_from_text(raw)
        if not isinstance(tasks, list) or not tasks:
            raise ValueError("Empty task list")
        print(f"\033[95m[Planner]: {len(tasks)} steps created\033[0m")
    except Exception as e:
        print(f"\033[91m[Planner Error]: {e}\033[0m")
        tasks = [{"step": 1, "description": goal, "instruction": goal}]

    # Display the plan to the user — do not start execution yet
    plan_text = t("core.planner.plan_for", goal=goal)
    for tsk in tasks:
        plan_text += f"{tsk['step']}. {tsk['description']}\n"
    plan_text += t("core.planner.start_prompt")

    # Save the plan to the SQLite state db — the pre_check_node will load itturn_thought
    try:
        from memory.pending_plans import save_pending_plan
        pending_user_key = _planner_pending_user_key(state)
        save_pending_plan(goal, tasks, user_id=pending_user_key)
        print(f"\033[95m[Planner]: Plan saved to SQLite pending_plans — awaiting confirmation\033[0m")
    except Exception as e:
        print(f"\033[91m[Planner]: Error saving pending plan: {e}\033[0m")

    return {
        "messages":                    [AIMessage(content=plan_text)],
        "plan_awaiting_confirmation":   True,
        "plan_goal":                   goal,
    }


# ────────────────────────────────────────────────────────────────
# Task Executor Node — executes one task at a time
# ────────────────────────────────────────────────────────────────

def task_executor_node(state):
    """
    Executes the current task from the plan.
    If there are results from previous steps, it passes them as context.
    """
    tasks        = state.get("plan_tasks", [])
    idx          = state.get("plan_index", 0)
    results      = state.get("plan_results", [])
    goal         = state.get("plan_goal", "")

    # If we are done → unusual situation, the graph will route to end_check
    if idx >= len(tasks):
        return {"plan_active": False}

    task = tasks[idx]
    print(f"\033[95m[TaskExecutor]: Step {idx+1}/{len(tasks)}: {task['description']}\033[0m")

    # We build context from previous results
    context = ""
    if results:
        context = t("prompts.ext_str_9")
        for i, r in enumerate(results[-3:]):  # last 3 only
            context += t("core.planner.step_prefix", step=i+1, result=r[:300])
        context += t("prompts.ext_str_97")

    instruction = (
        f"{context}"
        f"[PLAN STEP {idx+1}/{len(tasks)}]: {task['instruction']}\n\n" +
        t("core.planner.execute_only")
    )

    # Routing: we use capability_lookup to find the correct agent
    try:
        from core.capability_lookup import lookup_agent
        agent = lookup_agent(task["instruction"]) or "Dev_Agent"
    except Exception:
        agent = "Dev_Agent"

    print(f"[95m[TaskExecutor]: Routing step {idx+1} → {agent}[0m")

    # Progress indicator
    progress_msg = t("core.planner.step_progress", step=idx+1, total=len(tasks), desc=task['description'])

    return {
        "messages":   [AIMessage(content=progress_msg), HumanMessage(content=instruction)],
        "plan_index": idx,
        "next_agent": agent,
    }


# ────────────────────────────────────────────────────────────────
# Capture Result Node — after the agent, stores result
# ────────────────────────────────────────────────────────────────

def capture_result_node(state):
    """
    Runs after the agent, stores the result, and proceeds to the next step.
    """
    from core.utils import clean_message

    tasks   = state.get("plan_tasks", [])
    idx     = state.get("plan_index", 0)
    results = list(state.get("plan_results", []))

    # Find the agent's result — ignore ⏳ progress msgs
    last_result = ""
    for msg in reversed(state["messages"]):
        content = clean_message(getattr(msg, "content", ""))
        if content and getattr(msg, "type", "") == "ai" and not content.startswith("⏳"):
            last_result = content
            break

    results.append(last_result[:800] if last_result else t("prompts.ext_str_84"))
    new_idx = idx + 1

    print(f"\033[95m[TaskExecutor]: ✅ Step {idx+1} completed ({len(results)}/{len(tasks)})\033[0m")

    plan_active = new_idx < len(tasks)
    return {
        "plan_index":   new_idx,
        "plan_results": results,
        "plan_active":  plan_active,
    }


def _plan_summary(goal: str, tasks: list, results: list) -> dict:
    """Creates a summary and stores the post-plan reflection."""
    summary = t("core.planner.plan_completed", goal=goal)
    for i, (task, result) in enumerate(zip(tasks, results)):
        summary += f"**{i+1}. {task['description']}**\n{result[:500]}\n\n"

    print(f"\033[92m[Planner]: Plan completed — {len(tasks)} steps\033[0m")

    # Post-plan reflection
    try:
        from services.gemini import safe_gemini_call
        from services.reflection_engine import _save_reflection

        steps_text = "\n".join(f"{i+1}. {t['description']}: {r[:200]}" for i,(t,r) in enumerate(zip(tasks, results)))
        from core.utils import load_agent_prompt
        base_prompt = load_agent_prompt("planner_reflect")
        reflect_prompt = base_prompt.format(goal=goal, steps_text=steps_text)

        resp = safe_gemini_call(reflect_prompt)
        from core.utils import extract_json_from_text
        data = extract_json_from_text(resp.text)
        if not isinstance(data, dict):
            data = {}
        _save_reflection(
            source="planner",
            observation=data.get("observation", ""),
            action=data.get("action", ""),
            confidence=float(data.get("confidence", 0.7)),
            lesson=data.get("lesson", ""),
        )
        print(f"\033[92m[Planner]: Post-plan reflection saved\033[0m")
    except Exception as e:
        print(f"\033[90m[Planner]: Reflection skip: {e}\033[0m")

    return {
        "messages":    [AIMessage(content=summary)],
        "plan_active": False,
        "plan_tasks":  [],
        "plan_index":  0,
        "plan_results": [],
    }


# ────────────────────────────────────────────────────────────────
# Pre-Check Node — runs BEFORE the supervisor in each turn
# Checks if there is a pending plan and if the user confirmed
# ────────────────────────────────────────────────────────────────

def pre_check_node(state):
    """
    Entry point of the graph. Checks the pending plan in SQLite and routes:
    - "yes" + pending  → loads plan, route: task_executor
    - "no" + pending  → deletes plan, route: cancel
    - other / no pending → route: supervisor (normal flow)
    """
    from core.utils import clean_message

    last_msg = clean_message(state["messages"][-1].content)
    # Remove timestamp [HH:MM]
    last_msg = re.sub(r'^\[\d{1,2}:\d{2}\]\s*', '', last_msg).strip().lower()
    # Normalization: removal of unnecessary punctuation marks
    last_msg_norm = last_msg.rstrip("!.;").strip()

    from memory.pending_plans import get_pending_plan, clear_pending_plan

    pending_user_key = _planner_pending_user_key(state)
    pending = get_pending_plan(user_id=pending_user_key)
    if not pending:
        return {}

    # ── Confirmation ──────────────────────────────────────────────
    if last_msg in config.NLP_CONFIG.get("intents", {}).get("confirm_words", []) or last_msg_norm in config.NLP_CONFIG.get("intents", {}).get("confirm_words", []):
        try:
            clear_pending_plan(user_id=pending_user_key)
            print(f"\033[95m[PreCheck]: ✅ Plan confirmed — {len(pending['tasks'])} steps\033[0m")
            return {
                "plan_tasks":                  pending["tasks"],
                "plan_index":                  0,
                "plan_results":                [],
                "plan_active":                 True,
                "plan_goal":                   pending["goal"],
                "plan_awaiting_confirmation":  False,
                "next_agent":                  "__plan_confirmed__",
            }
        except Exception as e:
            print(f"\033[91m[PreCheck]: Error loading pending plan: {e}\033[0m")

    # ── Cancel ───────────────────────────────────────────────────
    elif last_msg in config.NLP_CONFIG.get("intents", {}).get("cancel_words", []) or last_msg_norm in config.NLP_CONFIG.get("intents", {}).get("cancel_words", []):
        try:
            clear_pending_plan(user_id=pending_user_key)
        except Exception:
            pass
        print(f"\033[95m[PreCheck]: ❌ Plan cancelled from the user\033[0m")
        return {
            "plan_awaiting_confirmation": False,
            "next_agent": "__plan_cancelled__",
        }

    # ── Another message while there is a pending one → leave it alive ─────────
    print("\033[90m[PreCheck]: Pending plan preserved (non-confirm/non-cancel message)\033[0m")
    return {}


def cancel_plan_node(state):
    """Returns a plan cancellation message."""
    return {"messages": [AIMessage(content=t("prompts.ext_plan_2"))], "plan_awaiting_confirmation": False}


# ────────────────────────────────────────────────────────────────
# Validate Step Node — checks if the last step succeeded
# ────────────────────────────────────────────────────────────────

from core.nl_config import PLANNER_FAILURE_WORDS
_FAILURE_SIGNALS = PLANNER_FAILURE_WORDS


def validate_step_node(state):
    """
    Executed after each agent during a plan.
    Checks if the response indicates failure (heuristic).
    - Failure -> AIMessage warning + plan_step_failed=True
    - Success -> plan_step_failed=False (no message)
    """
    from core.utils import clean_message

    if not state.get("plan_active"):
        return {}

    tasks = state.get("plan_tasks", [])
    idx   = state.get("plan_index", 0)

    if idx >= len(tasks):
        return {}

    task = tasks[idx]

    # Find the agent's last response (we ignore our own progress msgs)
    last_result = ""
    for msg in reversed(state["messages"]):
        if getattr(msg, "type", "") == "ai":
            content = clean_message(msg.content)
            if content and not content.startswith("⏳"):
                last_result = content
                break

    # We also check the last tool output (ToolMessage) for error signals
    last_tool_result = ""
    for msg in reversed(state["messages"]):
        if getattr(msg, "type", "") == "tool" or msg.__class__.__name__ == "ToolMessage":
            content = clean_message(getattr(msg, "content", ""))
            if content:
                last_tool_result = content
                break

    check_text = (last_result + " " + last_tool_result).lower()
    detected_failure = any(sig in check_text for sig in _FAILURE_SIGNALS)

    if detected_failure:
        warning = (
            t("core.planner.problem_detected", step=idx+1, total=len(tasks), desc=task["description"])
        )
        print(f"\033[93m[ValidateStep]: Step {idx+1} — failure signal detected\033[0m")
        return {
            "messages":         [AIMessage(content=warning)],
            "plan_step_failed": True,
        }

    print(f"\033[92m[ValidateStep]: Step {idx+1} — OK\033[0m")
    return {"plan_step_failed": False}


# ────────────────────────────────────────────────────────────────
# Replan Node — auto-skip of failed step
# ────────────────────────────────────────────────────────────────

def replan_node(state):
    """
    Called when validate_step detects a failure.
    Auto-skip: skips the failed step and continues to the next one.
    If there is no next step → plan_active=False → graph → end_check.
    """
    tasks   = state.get("plan_tasks", [])
    idx     = state.get("plan_index", 0)
    results = list(state.get("plan_results", []))
    skipped = list(state.get("replan_skipped_steps", []))

    task_desc = tasks[idx]["description"] if idx < len(tasks) else t("core.planner.step_name", step=idx+1)

    # Record skip
    skipped.append(idx)
    results.append(t("core.planner.skipped", desc=task_desc))

    new_idx    = idx + 1
    plan_active = new_idx < len(tasks)

    action_msg = ""
    if plan_active:
        action_msg = t("core.planner.skipped_msg", step=idx+1, desc=task_desc, next_step=new_idx+1)
    else:
        action_msg += t("prompts.ext_str_37")

    print(f"\033[93m[Replan]: Step {idx+1} skipped → {'task_executor' if plan_active else 'end_check'}\033[0m")

    return {
        "messages":             [AIMessage(content=action_msg)],
        "plan_index":           new_idx,
        "plan_results":         results,
        "plan_active":          plan_active,
        "plan_step_failed":     False,
        "replan_skipped_steps": skipped,
    }


# ────────────────────────────────────────────────────────────────
# End Check Node — final summary + reflection
# ────────────────────────────────────────────────────────────────

def end_check_node(state):
    """
    Runs after the end of ALL steps (successful or skipped).
    Creates a final summary, saves post-plan reflection.
    """
    goal    = state.get("plan_goal", "")
    tasks   = state.get("plan_tasks", [])
    results = state.get("plan_results", [])
    skipped = state.get("replan_skipped_steps", [])

    skipped_count = len(skipped)
    total         = len(tasks)
    success_count = total - skipped_count

    if skipped_count == 0:
        header = t("core.planner.plan_completed", goal=goal)
    else:
        header = (
            t("core.planner.plan_completed_stats", success=success_count, total=total, goal=goal)
        )

    summary = header
    for i, task in enumerate(tasks):
        result     = results[i] if i < len(results) else t("prompts.ext_str_84")
        skip_badge = t("prompts.ext_str_89") if i in skipped else ""
        summary   += f"**{i + 1}. {task['description']}**{skip_badge}\n{result[:500]}\n\n"

    print(f"\033[92m[EndCheck]: Plan done — {success_count}/{total} steps successful\033[0m")

    # Post-plan reflection
    try:
        from services.gemini import safe_gemini_call
        from services.reflection_engine import _save_reflection

        steps_text = "\n".join(
            f"{i+1}. {t['description']}: {(results[i] if i < len(results) else '')[:200]}"
            for i, t in enumerate(tasks)
        )
        from core.utils import load_agent_prompt
        base_prompt = load_agent_prompt("planner_reflect")
        reflect_prompt = base_prompt.format(goal=goal, steps_text=steps_text)
        resp = safe_gemini_call(reflect_prompt)
        raw  = re.sub(r"```json|```", "", resp.text.strip()).strip()
        data = json.loads(raw)
        _save_reflection(
            source="planner",
            observation=data.get("observation", ""),
            action=data.get("action", ""),
            confidence=float(data.get("confidence", 0.7)),
            lesson=data.get("lesson", ""),
        )
        print(f"\033[92m[EndCheck]: Post-plan reflection saved\033[0m")
    except Exception as e:
        print(f"\033[90m[EndCheck]: Reflection skip: {e}\033[0m")

    return {
        "messages":             [AIMessage(content=summary)],
        "plan_active":          False,
        "plan_tasks":           [],
        "plan_index":           0,
        "plan_results":         [],
        "replan_skipped_steps": [],
    }

