import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tool_risk import get_risk, TOOL_RISK
from core.approval import approval_check_node, _effective_risk, _notify_telegram_notify

# tool_risk checks
assert get_risk("read_local_file") == "SAFE", "read_local_file should be SAFE"
assert get_risk("set_reminder") == "WARNING", "set_reminder should be WARNING"
assert get_risk("google_calendar_tool") == "NOTIFY", "google_calendar_tool should be NOTIFY"
assert get_risk("drive_manager") == "NOTIFY", "drive_manager should be NOTIFY"
assert get_risk("execute_local_pipeline") == "CRITICAL", "execute_local_pipeline should be CRITICAL"
assert get_risk("mail_manager") == "CRITICAL", "mail_manager should be CRITICAL"

# _effective_risk drive_manager subtypes
assert _effective_risk({"name": "drive_manager", "args": {"action": "list_files"}}) == "SAFE"
assert _effective_risk({"name": "drive_manager", "args": {"action": "upload"}}) == "NOTIFY"
assert _effective_risk({"name": "drive_manager", "args": {"action": "delete"}}) == "CRITICAL"

# _notify_telegram_notify callable
assert callable(_notify_telegram_notify)

print("OK — all checks passed")
