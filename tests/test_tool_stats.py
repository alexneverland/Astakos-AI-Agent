"""
Tests για το tool_stats tool.
Τρέξε: venv/Scripts/python.exe tests/test_tool_stats.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from tools.system import tool_stats

errors = []

# 1. Επιστρέφει string
result = tool_stats.invoke({"days": 7})
assert isinstance(result, str), "Πρέπει να επιστρέφει string"
print(f"✅ Επιστρέφει string ({len(result)} chars)")

# 2. Περιέχει header
assert "📊" in result or "Tool Stats" in result or "traces" in result, \
    f"Αναμενόταν header στο αποτέλεσμα:\n{result[:200]}"
print("✅ Header υπάρχει")

# 3. days=0 → δεν κρασάρει
result0 = tool_stats.invoke({"days": 0})
assert isinstance(result0, str)
print("✅ days=0 δεν κρασάρει")

# 4. days=1 → δεν κρασάρει
result1 = tool_stats.invoke({"days": 1})
assert isinstance(result1, str)
print("✅ days=1 δεν κρασάρει")

# 5. Αποτέλεσμα περιέχει error rate αν υπάρχουν traces
if "κλήσεις" in result:
    assert "σφάλματα" in result, "Αν υπάρχουν tools, πρέπει να δείχνει σφάλματα"
    print("✅ Format 'κλήσεις / σφάλματα' υπάρχει")
else:
    print("ℹ️  Δεν βρέθηκαν traces — skip format check")

if errors:
    print(f"\n❌ {len(errors)} αποτυχίες:")
    for e in errors: print(f"  - {e}")
    sys.exit(1)
else:
    print("\n✅ Όλα τα tests πέρασαν!")
