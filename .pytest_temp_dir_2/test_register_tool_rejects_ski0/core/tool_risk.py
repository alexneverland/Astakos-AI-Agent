TOOL_RISK = {
    "register_tool": "CRITICAL",
}

def get_risk(name): return TOOL_RISK.get(name, "WARNING")
def is_critical(name): return get_risk(name) == "CRITICAL"
