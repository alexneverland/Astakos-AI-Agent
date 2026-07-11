"""
Tests for the read_local_file whitelist — source dirs + blocklist.
Run: venv/Scripts/python.exe tests/test_read_local_whitelist.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from tools.system import read_local_file

def invoke(path):
    return read_local_file.invoke({"file_path": path})

errors = []

def check(desc, result, expect_ok: bool):
    ok = not result.startswith("❌")
    if ok == expect_ok:
        status = "✅ OK" if expect_ok else "✅ BLOCKED"
        print(f"{status}: {desc}")
    else:
        msg = f"{'ALLOW' if expect_ok else 'BLOCK'} απέτυχε για: {desc} → {result[:80]}"
        errors.append(msg)
        print(f"❌ {msg}")

# --- Source dirs: must be allowed ---
check("tools/system.py",        invoke("tools/system.py"),        expect_ok=True)
check("tools/web.py",           invoke("tools/web.py"),           expect_ok=True)
check("core/approval.py",       invoke("core/approval.py"),       expect_ok=True)
check("core/tool_risk.py",      invoke("core/tool_risk.py"),      expect_ok=True)
check("memory/context_builder.py", invoke("memory/context_builder.py"), expect_ok=True)
check("memory/execution_trace.py", invoke("memory/execution_trace.py"), expect_ok=True)

# --- Sensitive files: must be blocked ---
check("config.py (blocked)",    invoke("config.py"),              expect_ok=False)
check(".env (blocked)",         invoke(".env"),                   expect_ok=False)

# --- .db files: must be blocked ---
import config as cfg
db_path = os.path.join(cfg.BASE_DIR, "astakos_embeddings_cache.db")
if os.path.exists(db_path):
    check(".db file (blocked)", invoke(db_path),                  expect_ok=False)
else:
    print("ℹ️  .db file does not exist — skip")

# --- Files not in whitelist: must be blocked ---
check("C:/Windows/system32/drivers/etc/hosts (blocked)",
      invoke("C:/Windows/system32/drivers/etc/hosts"),            expect_ok=False)

if errors:
    print(f"\n❌ {len(errors)} failures:")
    for e in errors: print(f"  - {e}")
    sys.exit(1)
else:
    print("\n✅ All tests passed!")
