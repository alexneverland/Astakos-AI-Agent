# ================================================================
# Project: Astakos AI Agent 🦞
# Skill:   register_tool — Auto-registration νέων tools
# Καταχωρεί tool σε system.py, tool_risk.py, capability_registry.json
# ================================================================
import os
import json
from langchain_core.tools import tool


@tool
def register_tool(
    tool_name: str,
    description: str = "",
    agent: str = "Dev_Agent",
    risk: str = "WARNING",
    triggers: str = "",
) -> str:
    """
    Καταχωρεί αυτόματα ένα νέο tool που βρίσκεται στο astakos_skills/ σε όλα τα απαραίτητα σημεία:
    1. tools/system.py  — import + all_tools list
    2. core/tool_risk.py — risk level
    3. core/capability_registry.json — agent routing + triggers

    tool_name:   Το όνομα του tool (ίδιο με το filename και τη function, π.χ. 'my_tool')
    description: Σύντομη περιγραφή για το capability registry
    agent:       Ποιος agent το χειρίζεται (default: Dev_Agent)
    risk:        SAFE / WARNING / CRITICAL (default: WARNING)
    triggers:    Comma-separated λέξεις-κλειδιά για routing (π.χ. 'my tool, κάνε x, do x')
    """
    from config import BASE_DIR

    tool_name   = tool_name.strip()
    risk        = risk.strip().upper()
    agent       = agent.strip()
    description = description.strip()

    if risk not in ("SAFE", "WARNING", "CRITICAL"):
        return f"❌ Μη έγκυρο risk: '{risk}'. Επίτρεπτα: SAFE, WARNING, CRITICAL."

    skill_path = os.path.join(BASE_DIR, "astakos_skills", f"{tool_name}.py")
    if not os.path.exists(skill_path):
        return f"❌ Δεν βρέθηκε το αρχείο: astakos_skills/{tool_name}.py"

    results = []

    # ── 1. tools/system.py ──────────────────────────────────────
    sys_path = os.path.join(BASE_DIR, "tools", "system.py")
    with open(sys_path, "r", encoding="utf-8") as f:
        sys_content = f.read()

    import_line = f"from astakos_skills.{tool_name} import {tool_name}"

    if import_line in sys_content:
        results.append(f"⚠️  system.py: import ήδη υπάρχει")
    else:
        # Εισαγωγή μετά από το τελευταίο astakos_skills import
        last_import = "from astakos_skills.register_tool import register_tool"
        if last_import in sys_content:
            sys_content = sys_content.replace(
                last_import,
                f"{last_import}\n{import_line}",
                1
            )
            results.append(f"✅ system.py: import προστέθηκε")
        else:
            results.append(f"⚠️  system.py: δεν βρέθηκε anchor για import — πρόσθεσε χειροκίνητα: {import_line}")

    if f"    {tool_name}," in sys_content or f", {tool_name}," in sys_content:
        results.append(f"⚠️  system.py: all_tools ήδη περιέχει {tool_name}")
    else:
        # Εισαγωγή πριν το κλείσιμο ]
        sys_content = sys_content.replace(
            "    register_tool,\n]",
            f"    {tool_name},\n    register_tool,\n]",
            1
        )
        results.append(f"✅ system.py: προστέθηκε στο all_tools")

    # system.py θα γραφτεί ΤΕΛΕΥΤΑΙΟ μετά το registry

    # ── 2. core/tool_risk.py ────────────────────────────────────
    risk_path = os.path.join(BASE_DIR, "core", "tool_risk.py")
    with open(risk_path, "r", encoding="utf-8") as f:
        risk_content = f.read()

    risk_line = f'    "{tool_name}":'
    if risk_line in risk_content:
        results.append(f"⚠️  tool_risk.py: {tool_name} ήδη υπάρχει")
    else:
        insert_before = '}\n\ndef get_risk'
        new_entry = f'    "{tool_name}":{" " * max(1, 24 - len(tool_name))}"{risk}",\n'
        risk_content = risk_content.replace(
            insert_before,
            new_entry + insert_before,
            1
        )
        risk_content = risk_content.replace("\r\n", "\n").replace("\n", "\r\n")
        with open(risk_path, "wb") as f:
            f.write(risk_content.encode("utf-8"))
        results.append(f"✅ tool_risk.py: {tool_name} → {risk}")

    # ── 3. core/capability_registry.json ────────────────────────
    registry_path = os.path.join(BASE_DIR, "core", "capability_registry.json")
    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            registry = json.load(f)

        if any(e["name"] == tool_name for e in registry):
            results.append(f"⚠️  capability_registry: {tool_name} ήδη υπάρχει")
        else:
            trigger_list = [t.strip() for t in triggers.split(",") if t.strip()] if triggers else [tool_name.replace("_", " ")]
            registry.insert(0, {
                "name":        tool_name,
                "description": description or f"Tool: {tool_name}",
                "agent":       agent,
                "priority":    9,
                "triggers":    trigger_list,
            })
            with open(registry_path, "w", encoding="utf-8") as f:
                json.dump(registry, f, ensure_ascii=False, indent=2)
            results.append(f"✅ capability_registry: {tool_name} → {agent} ({len(trigger_list)} triggers)")
    except Exception as e:
        results.append(f"⚠️  capability_registry error: {e}")

    # ── system.py ΤΕΛΕΥΤΑΙΟ — debounce ξεκινά εδώ ────────────────
    sys_content = sys_content.replace("\r\n", "\n").replace("\n", "\r\n")
    with open(sys_path, "wb") as f:
        f.write(sys_content.encode("utf-8"))

    summary = "\n".join(results)
    return (
        f"🔧 register_tool: '{tool_name}'\n"
        f"{summary}\n\n"
        f"⚡ Ο server θα κάνει auto-restart για να φορτώσει το νέο tool."
    )


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: register_tool.py <tool_name> [agent] [risk] [triggers]")
        sys.exit(1)
    name    = sys.argv[1]
    ag      = sys.argv[2] if len(sys.argv) > 2 else "Dev_Agent"
    rk      = sys.argv[3] if len(sys.argv) > 3 else "WARNING"
    trg     = sys.argv[4] if len(sys.argv) > 4 else ""
    print(register_tool.func(tool_name=name, agent=ag, risk=rk, triggers=trg))
