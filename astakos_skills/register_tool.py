# ================================================================
# Project: Astakos AI Agent 🦞
# Skill:   register_tool — Auto-registration of new tools
# Registers tool in system.py, tool_risk.py, capability_registry.json
# ================================================================
import os
import json
import re
import difflib
import ast
from langchain_core.tools import tool
from core.i18n import t


def _unified_diff(label: str, before: str, after: str) -> str:
    if before == after:
        return ""
    return "\n".join(difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"a/{label}",
        tofile=f"b/{label}",
        lineterm="",
    ))


def _decorator_name(decorator) -> str:
    if isinstance(decorator, ast.Call):
        return _decorator_name(decorator.func)
    if isinstance(decorator, ast.Name):
        return decorator.id
    if isinstance(decorator, ast.Attribute):
        base = _decorator_name(decorator.value)
        return f"{base}.{decorator.attr}" if base else decorator.attr
    return ""


def _validate_skill_tool(skill_path: str, tool_name: str) -> str:
    try:
        with open(skill_path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
    except SyntaxError as exc:
        return f"Skill syntax error on line {exc.lineno}: {exc.msg}"
    except Exception as exc:
        return f"Could not read skill file: {exc}"

    functions = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    matching = [node for node in functions if node.name == tool_name]
    if len(matching) != 1:
        return f"Skill must contain exactly one top-level function named '{tool_name}'."

    has_tool = any(
        _decorator_name(dec).split(".")[-1] == "tool"
        for dec in matching[0].decorator_list
    )
    if not has_tool:
        return (
            f"Function '{tool_name}' must have @tool. "
            "Create or rewrite the skill with write_custom_tool first."
        )

    extra_tools = [
        node.name for node in functions
        if node.name != tool_name and any(
            _decorator_name(dec).split(".")[-1] == "tool"
            for dec in node.decorator_list
        )
    ]
    if extra_tools:
        return f"Only one @tool function is allowed. Extra tools: {', '.join(extra_tools)}."

    return ""


@tool
def register_tool(
    tool_name: str,
    description: str = "",
    agent: str = "Dev_Agent",
    risk: str = "WARNING",
    triggers: str = "",
    dry_run: bool = False,
) -> str:
    """
    Automatically registers a new tool located in astakos_skills/ in all necessary locations:
    1. tools/system.py  — import + all_tools list
    2. core/tool_risk.py — risk level
    3. core/capability_registry.json — agent routing + triggers

    tool_name:   The name of the tool (same as the filename and the function, e.g., 'my_tool')
    description: Short description for the capability registry
    agent:       Which agent handles it (default: Dev_Agent)
    risk:        SAFE / WARNING / CRITICAL (default: WARNING)
    triggers:    Comma-separated keywords for routing (e.g., 'my tool, do x, do y')
    dry_run:     True = preview only, no files are changed. False = apply changes.
    """
    from config import BASE_DIR

    tool_name   = tool_name.strip()
    risk        = risk.strip().upper()
    agent       = agent.strip()
    description = description.strip()
    if isinstance(dry_run, str):
        dry_run = dry_run.strip().lower() in ("1", "true", "yes", "y", "nai", t("prompts.ext_str_802"))

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", tool_name):
        return "System Error: invalid tool_name. Use a Python identifier, e.g. my_tool."

    if risk not in ("SAFE", "WARNING", "NOTIFY", "CRITICAL"):
        return t("skills.register_tool.msg_invalid_risk", risk=risk)

    skills_dir = os.path.realpath(os.path.join(BASE_DIR, "astakos_skills"))
    skill_path = os.path.realpath(os.path.join(skills_dir, f"{tool_name}.py"))
    if not skill_path.startswith(skills_dir + os.sep):
        return "System Error: invalid skill path."
    if not os.path.exists(skill_path):
        return t("skills.register_tool.msg_file_not_found", tool=tool_name)

    validation_error = _validate_skill_tool(skill_path, tool_name)
    if validation_error:
        return (
            f"System Error: astakos_skills/{tool_name}.py is not a valid tool skill.\n"
            f"{validation_error}\n"
            "No files were changed."
        )

    results = []
    errors = []
    diffs = []

    # ── 1. tools/system.py ──────────────────────────────────────
    sys_path = os.path.join(BASE_DIR, "tools", "system.py")
    with open(sys_path, "r", encoding="utf-8") as f:
        sys_content = f.read()
    sys_original = sys_content

    import_line = f"from astakos_skills.{tool_name} import {tool_name}"

    if import_line in sys_content:
        results.append(f"⚠️  system.py: import already exists")
    else:
        # Import after the last astakos_skills import
        last_import = "from astakos_skills.register_tool import register_tool"
        if last_import in sys_content:
            sys_content = sys_content.replace(
                last_import,
                f"{last_import}\n{import_line}",
                1
            )
            results.append(
                f"DRY RUN system.py: would add import {import_line}"
                if dry_run else
                f"✅ system.py: import added"
            )
        else:
            errors.append(f"system.py: missing import anchor `{last_import}`")
            results.append(f"⚠️  system.py: import anchor not found — add manually: {import_line}")

    if f"    {tool_name}," in sys_content or f", {tool_name}," in sys_content:
        results.append(f"⚠️  system.py: all_tools already contains {tool_name}")
    else:
        # Insert before the closing ]
        if "]" in sys_content:
            sys_content = sys_content.replace(
                "\n]",
                f"\n    {tool_name},\n]",
                1
            )
            results.append(
                f"DRY RUN system.py: would add {tool_name} to all_tools"
                if dry_run else
                f"✅ system.py: added to all_tools"
            )
        else:
            errors.append(f"system.py: missing all_tools anchor `]`")
            results.append(f"⚠️  system.py: all_tools anchor not found — add manually: {tool_name}")

    # system.py will be written LAST after registry

    # ── 2. core/tool_risk.py ────────────────────────────────────
    risk_path = os.path.join(BASE_DIR, "core", "tool_risk.py")
    with open(risk_path, "r", encoding="utf-8") as f:
        risk_content = f.read()
    risk_original = risk_content

    risk_line = f'    "{tool_name}":'
    if risk_line in risk_content:
        results.append(f"⚠️  tool_risk.py: {tool_name} already exists")
    else:
        insert_before = '}\n\ndef get_risk'
        new_entry = f'    "{tool_name}":{" " * max(1, 24 - len(tool_name))}"{risk}",\n'
        if insert_before in risk_content:
            risk_content = risk_content.replace(
                insert_before,
                new_entry + insert_before,
                1
            )
            results.append(
                f"DRY RUN tool_risk.py: would add {tool_name} -> {risk}"
                if dry_run else
                f"✅ tool_risk.py: {tool_name} → {risk}"
            )
        else:
            errors.append(f"tool_risk.py: missing risk insert anchor `{insert_before}`")
            results.append(f"⚠️  tool_risk.py: risk insert anchor not found")

    # ── 3. core/capability_registry.json ────────────────────────
    registry_path = os.path.join(BASE_DIR, "core", "capability_registry.json")
    registry_content = ""
    registry_new_content = ""
    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            registry_content = f.read()
            registry = json.loads(registry_content)

        if any(e["name"] == tool_name for e in registry):
            results.append(f"⚠️  capability_registry: {tool_name} already exists")
            registry_new_content = registry_content
        else:
            trigger_list = [t.strip() for t in triggers.split(",") if t.strip()] if triggers else [tool_name.replace("_", " ")]
            registry.insert(0, {
                "name":        tool_name,
                "description": description or f"Tool: {tool_name}",
                "agent":       agent,
                "risk_level":  risk,
                "priority":    9,
                "triggers":    trigger_list,
            })
            registry_new_content = json.dumps(registry, ensure_ascii=False, indent=2)
            results.append(
                f"DRY RUN capability_registry: would add {tool_name} -> {agent} ({len(trigger_list)} triggers)"
                if dry_run else
                f"✅ capability_registry: {tool_name} → {agent} ({len(trigger_list)} triggers)"
            )
    except Exception as e:
        errors.append(f"capability_registry.json: {e}")
        results.append(f"⚠️  capability_registry error: {e}")

    # ── system.py LAST — debounce starts here ────────────────_
    for label, before, after in (
        ("tools/system.py", sys_original, sys_content),
        ("core/tool_risk.py", risk_original, risk_content),
        ("core/capability_registry.json", registry_content, registry_new_content or registry_content),
    ):
        diff = _unified_diff(label, before, after)
        if diff:
            diffs.append(f"```diff\n{diff}\n```")

    if errors:
        summary = "\n".join(results)
        error_text = "\n".join(f"- {e}" for e in errors)
        return (
            f"🔧 register_tool: '{tool_name}'\n" +
            f"{summary}\n\n" +
            t("skills.register_tool.msg_nothing_applied") +
            f"{error_text}\n\n" +
            f"No files were changed."
        )

    if not dry_run:
        if risk_content != risk_original:
            risk_content = risk_content.replace("\r\n", "\n").replace("\n", "\r\n")
            with open(risk_path, "wb") as f:
                f.write(risk_content.encode("utf-8"))
        if registry_new_content and registry_new_content != registry_content:
            with open(registry_path, "w", encoding="utf-8") as f:
                f.write(registry_new_content)
        sys_content = sys_content.replace("\r\n", "\n").replace("\n", "\r\n")
        with open(sys_path, "wb") as f:
            f.write(sys_content.encode("utf-8"))

    summary = "\n".join(results)
    mode = "DRY RUN " if dry_run else ""
    diff_text = ("\n\nDIFF PREVIEW:\n" + "\n\n".join(diffs)) if dry_run and diffs else ""
    footer = (
        "No files were changed. Run again with dry_run=False to apply."
        if dry_run else
        t("skills.register_tool.restart_notice")
    )
    return (
        f"🔧 {mode}register_tool: '{tool_name}'\n"
        f"{summary}{diff_text}\n\n"
        f"{footer}"
    )


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: register_tool.py <tool_name> [agent] [risk] [triggers] [dry_run]")
        sys.exit(1)
    name    = sys.argv[1]
    ag      = sys.argv[2] if len(sys.argv) > 2 else "Dev_Agent"
    rk      = sys.argv[3] if len(sys.argv) > 3 else "WARNING"
    trg     = sys.argv[4] if len(sys.argv) > 4 else ""
    dry     = sys.argv[5] if len(sys.argv) > 5 else False
    print(register_tool.func(tool_name=name, agent=ag, risk=rk, triggers=trg, dry_run=dry))

