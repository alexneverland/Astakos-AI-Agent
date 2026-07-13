from langchain_core.tools import tool
import json
import os

@tool
def manage_context_flag(action: str, flag_key: str, description: str = "") -> str:
    """
    Manage the system's context flags stored in astakos_context_schema.json.
    
    Use this tool when the user asks to explicitly create, edit, or delete a context flag.
    
    action: "add", "edit", or "delete".
    flag_key: The canonical name of the flag (e.g., "vacation_mode"). Must be lowercase with underscores.
    description: A clear description of when this flag applies (required for "add" or "edit").
    """
    from config import BASE_DIR
    import config
    
    schema_path = os.path.join(BASE_DIR, "astakos_context_schema.json")
    
    action = action.strip().lower()
    flag_key = flag_key.strip().lower()
    
    if action not in ["add", "edit", "delete"]:
        return "Error: action must be 'add', 'edit', or 'delete'."
        
    if action in ["add", "edit"] and not description:
        return f"Error: a description is required when action is '{action}'."
        
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
    except Exception as e:
        return f"Error reading schema file: {e}"
        
    flags = schema.get("flags", [])
    existing = next((f for f in flags if f.get("key") == flag_key), None)
    
    if action == "add":
        if existing:
            return f"Error: flag '{flag_key}' already exists."
        flags.append({"key": flag_key, "description": description})
        
    elif action == "edit":
        if not existing:
            return f"Error: flag '{flag_key}' does not exist."
        existing["description"] = description
        
    elif action == "delete":
        if not existing:
            return f"Error: flag '{flag_key}' does not exist."
        flags = [f for f in flags if f.get("key") != flag_key]
        schema["flags"] = flags
        
    try:
        with open(schema_path, "w", encoding="utf-8") as f:
            json.dump(schema, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except Exception as e:
        return f"Error writing schema file: {e}"
        
    # Attempt to dynamically update the config so it's instantly available without restart
    try:
        config.CONTEXT_SCHEMA = schema
        config.CANONICAL_CONTEXT_KEYS = {f["key"] for f in flags if "key" in f}
    except Exception:
        pass
        
    return f"Successfully {action}ed context flag '{flag_key}'."
