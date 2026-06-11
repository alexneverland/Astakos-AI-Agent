import json, sys, os
path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core", "capability_registry.json")
data = json.load(open(path, encoding="utf-8"))
valid_agents = {"Dev_Agent","Chat_Agent","Home_Agent","Web_Agent","Tech_Agent","Git_Agent","Mail_Agent"}
valid_risks  = {"SAFE","WARNING","NOTIFY","CRITICAL","DYNAMIC"}
errors = []
for cap in data:
    if cap.get("agent") not in valid_agents:
        errors.append(f"Unknown agent '{cap.get('agent')}' in '{cap['name']}'")
    if cap.get("risk_level") not in valid_risks:
        errors.append(f"Missing/invalid risk_level in '{cap['name']}'")
if errors:
    print("ERRORS:")
    for e in errors: print(" -", e)
    sys.exit(1)
print(f"OK — {len(data)} capabilities, all valid")
