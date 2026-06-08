# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Planning Agent
# Παίρνει goal → βγάζει structured task list → εκτελεί βήμα-βήμα
# ================================================================

import json
import re
from langchain_core.messages import HumanMessage, AIMessage


# ────────────────────────────────────────────────────────────────
# Planner Node — δημιουργεί task list από goal
# ────────────────────────────────────────────────────────────────

def planner_node(state):
    """
    Παίρνει το goal (μήνυμα μετά το /plan) και βγάζει structured task list.
    Αποθηκεύει στο state: plan_tasks, plan_index=0, plan_results=[]
    """
    from core.brain import llm_heavy, safe_llm_invoke
    from core.utils import clean_message

    last_msg = clean_message(state["messages"][-1].content)
    # Αφαιρούμε timestamp [HH:MM] και /plan prefix
    goal = re.sub(r'^\[\d{1,2}:\d{2}\]\s*', '', last_msg).strip()
    goal = re.sub(r'^/plan\b\s*', '', goal).strip()

    print(f"\033[95m[Planner]: Αναλύω goal: {goal[:80]}\033[0m")

    prompt = f"""Είσαι ο Αστακός, AI βοηθός. Ο χρήστης θέλει να εκτελέσεις το εξής:

GOAL: {goal}

Σπάσε το σε συγκεκριμένα, εκτελέσιμα βήματα. Κάθε βήμα πρέπει να είναι μια απλή εντολή που μπορεί να εκτελέσει ένας agent.

Απάντησε ΜΟΝΟ με JSON array, χωρίς markdown:
[
  {{"step": 1, "description": "Σύντομη περιγραφή", "instruction": "Ακριβής εντολή προς τον agent"}},
  {{"step": 2, "description": "...", "instruction": "..."}}
]

Μέγιστο 7 βήματα. Κάθε instruction να είναι σαφής και αυτόνομη."""

    try:
        response = safe_llm_invoke(llm_heavy, [HumanMessage(content=prompt)])
        raw = clean_message(response.content)
        raw = re.sub(r"```json|```", "", raw).strip()
        tasks = json.loads(raw)
        if not isinstance(tasks, list) or not tasks:
            raise ValueError("Empty task list")
        print(f"\033[95m[Planner]: {len(tasks)} βήματα δημιουργήθηκαν\033[0m")
    except Exception as e:
        print(f"\033[91m[Planner Error]: {e}\033[0m")
        tasks = [{"step": 1, "description": goal, "instruction": goal}]

    # Εμφανίζουμε το plan στον χρήστη
    plan_text = f"📋 **Plan για:** _{goal}_\n\n"
    for t in tasks:
        plan_text += f"{t['step']}. {t['description']}\n"
    plan_text += f"\n⚙️ Ξεκινάω εκτέλεση..."

    return {
        "messages":     [AIMessage(content=plan_text)],
        "plan_tasks":   tasks,
        "plan_index":   0,
        "plan_results": [],
        "plan_active":  True,
        "plan_goal":    goal,
    }


# ────────────────────────────────────────────────────────────────
# Task Executor Node — εκτελεί ένα task τη φορά
# ────────────────────────────────────────────────────────────────

def task_executor_node(state):
    """
    Εκτελεί το τρέχον task από το plan.
    Αν υπάρχουν αποτελέσματα προηγούμενων βημάτων, τα περνά ως context.
    """
    tasks        = state.get("plan_tasks", [])
    idx          = state.get("plan_index", 0)
    results      = state.get("plan_results", [])
    goal         = state.get("plan_goal", "")

    # Αν τελειώσαμε → summary
    if idx >= len(tasks):
        return _plan_summary(goal, tasks, results)

    task = tasks[idx]
    print(f"\033[95m[TaskExecutor]: Βήμα {idx+1}/{len(tasks)}: {task['description']}\033[0m")

    # Χτίζουμε context από προηγούμενα αποτελέσματα
    context = ""
    if results:
        context = "\n\n[ΑΠΟΤΕΛΕΣΜΑΤΑ ΠΡΟΗΓΟΥΜΕΝΩΝ ΒΗΜΑΤΩΝ]\n"
        for i, r in enumerate(results[-3:]):  # τελευταία 3 μόνο
            context += f"Βήμα {i+1}: {r[:300]}\n"
        context += "[/ΑΠΟΤΕΛΕΣΜΑΤΑ]\n\n"

    instruction = f"{context}[PLAN ΒΗΜΑ {idx+1}/{len(tasks)}]: {task['instruction']}"

    # Routing: χρησιμοποιούμε capability_lookup για να βρούμε τον σωστό agent
    try:
        from core.capability_lookup import lookup_agent
        agent = lookup_agent(task["instruction"]) or "Dev_Agent"
    except Exception:
        agent = "Dev_Agent"

    print(f"[95m[TaskExecutor]: Routing βήμα {idx+1} → {agent}[0m")

    return {
        "messages":   [HumanMessage(content=instruction)],
        "plan_index": idx,
        "next_agent": agent,
    }


# ────────────────────────────────────────────────────────────────
# Capture Result Node — μετά τον agent, αποθηκεύει αποτέλεσμα
# ────────────────────────────────────────────────────────────────

def capture_result_node(state):
    """
    Τρέχει μετά τον agent, αποθηκεύει το αποτέλεσμα και προχωράει στο επόμενο βήμα.
    """
    from core.utils import clean_message

    tasks   = state.get("plan_tasks", [])
    idx     = state.get("plan_index", 0)
    results = list(state.get("plan_results", []))

    # Βρίσκουμε το αποτέλεσμα του agent (τελευταίο AI message)
    last_result = ""
    for msg in reversed(state["messages"]):
        content = clean_message(getattr(msg, "content", ""))
        if content and getattr(msg, "type", "") == "ai":
            last_result = content
            break

    results.append(last_result[:800] if last_result else "(χωρίς αποτέλεσμα)")
    new_idx = idx + 1

    print(f"\033[95m[TaskExecutor]: ✅ Βήμα {idx+1} ολοκληρώθηκε ({len(results)}/{len(tasks)})\033[0m")

    if new_idx >= len(tasks):
        # Τελευταίο βήμα — βγάζουμε summary
        return _plan_summary(state.get("plan_goal", ""), tasks, results)

    return {
        "plan_index":   new_idx,
        "plan_results": results,
    }


def _plan_summary(goal: str, tasks: list, results: list) -> dict:
    """Δημιουργεί summary και αποθηκεύει post-plan reflection."""
    summary = f"✅ **Plan ολοκληρώθηκε:** _{goal}_\n\n"
    for i, (task, result) in enumerate(zip(tasks, results)):
        summary += f"**{i+1}. {task['description']}**\n{result[:500]}\n\n"

    print(f"\033[92m[Planner]: Plan ολοκληρώθηκε — {len(tasks)} βήματα\033[0m")

    # Post-plan reflection
    try:
        from services.gemini import safe_gemini_call
        from services.reflection_engine import _save_reflection

        steps_text = "\n".join(f"{i+1}. {t['description']}: {r[:200]}" for i,(t,r) in enumerate(zip(tasks, results)))
        reflect_prompt = f"""Ανέλυσε αυτό το ολοκληρωμένο plan και δώσε σύντομη αξιολόγηση.
Goal: {goal}
Steps:
{steps_text}

Απάντησε με JSON:
{{"observation": "τι παρατήρησες", "action": "τι θα βελτίωνες στο μέλλον", "confidence": 0.7, "lesson": "το lesson learned"}}
Μόνο JSON, χωρίς markdown."""

        resp = safe_gemini_call(reflect_prompt)
        import json, re
        raw = re.sub(r"```json|```", "", resp.text.strip()).strip()
        data = json.loads(raw)
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
