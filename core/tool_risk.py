# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Tool Risk Registry
# Κάθε tool έχει ένα risk level:
#   SAFE     → εκτελεί αμέσως, σιωπηλά (reads, queries)
#   WARNING  → εκτελεί αμέσως, log μόνο στο web UI (χωρίς Telegram)
#   NOTIFY   → εκτελεί αμέσως + Telegram info χωρίς approve/reject buttons
#   CRITICAL → μπλοκάρει + Telegram με ✅/❌ approve/reject
# ================================================================

TOOL_RISK: dict[str, str] = {
    # ── CRITICAL: destructive / external send / irreversible ────
    "run_terminal_command":     "DYNAMIC",  # risk καθορίζεται από classify_command() στο approval.py
    "github_manager":           "CRITICAL",
    "mail_manager":             "CRITICAL",
    "execute_local_pipeline":   "CRITICAL",
    "post_to_linkedin":         "CRITICAL",
    "process_and_clear_linkedin_post": "CRITICAL",
    "write_project_file":       "CRITICAL",  # full rewrite
    "register_tool":            "CRITICAL",  # τροποποιεί system.py + tool_risk.py
    "grant_project_access":     "CRITICAL",  # permanent permission change

    # ── NOTIFY: εκτελεί + Telegram info (χωρίς buttons) ─────────
    "drive_manager":            "NOTIFY",    # upload/download/rename — handled by _effective_risk
    "google_calendar_tool":     "SAFE",      # per-action risk handled by _effective_risk() in approval.py

    # ── WARNING: writes / side-effects — log μόνο στο web UI ────
    "save_goal_tool":           "WARNING",
    "update_goal_status_tool":  "WARNING",
    "delete_from_memory":       "WARNING",
    "control_vacuum":           "WARNING",
    "manage_list":              "WARNING",
    "set_local_reminder":       "WARNING",
    "google_tasks_tool":        "WARNING",
    "learn_routine":            "WARNING",
    "edit_routine":             "WARNING",
    "delete_routine":           "WARNING",
    "control_routine_notifications": "WARNING",
    "control_routine_schedule":  "WARNING",
    "control_routine_condition": "WARNING",
    "control_routine_cooldown":  "WARNING",
    "control_pending_followup":  "WARNING",
    "write_code":               "WARNING",
    "write_custom_tool":        "WARNING",
    "update_pending_linkedin_post": "WARNING",
    "relay_local_payload":      "WARNING",
    "save_to_memory":           "WARNING",
    "run_code":                 "WARNING",
    "log_meal":                 "WARNING",
    "control_spotify":          "WARNING",
    "generate_image_tool":      "WARNING",
    "archive_file":             "WARNING",
    "scan_receipt":             "WARNING",
    "edit_project_file":        "WARNING",   # escalates to CRITICAL για core files (approval.py)
    # ── SAFE: reads / queries / zero side-effects ────────────────
    "search_memory":            "SAFE",
    "retrieve_photo":           "SAFE",
    "read_local_file":          "SAFE",
    "get_news":                 "SAFE",
    "get_weather_forecast":     "SAFE",
    "duckduckgo_search":        "SAFE",
    "browse_url":               "SAFE",
    "research_last30days":      "SAFE",
    "search_google_places":     "SAFE",
    "get_navigation_info":      "SAFE",
    "search_goldmall_offers":   "SAFE",
    "search_supermarket_prices":"SAFE",
    "search_flights":           "SAFE",
    "get_fit_summary":          "SAFE",
    "get_routines":             "SAFE",
    "get_current_location":     "SAFE",
    "recipe_expert":            "SAFE",
    "repo_mapper":              "SAFE",
    "list_project_files":       "SAFE",
    "grep_project_files":       "SAFE",
    "read_project_file":        "SAFE",
    "list_recent_files":        "SAFE",
    "text_stats":               "SAFE",
    "tool_stats":               "SAFE",
    "system_doctor":            "SAFE",
    "memory_review":            "SAFE",
    "create_file_tool":         "SAFE",
    "generate_excel":           "SAFE",
    "generate_word_doc":        "SAFE",
    "generate_pdf":             "SAFE",
    "generate_csv":             "SAFE",
}

def get_risk(tool_name: str) -> str:
    """Επιστρέφει SAFE/WARNING/NOTIFY/CRITICAL. Default: WARNING αν άγνωστο."""
    return TOOL_RISK.get(tool_name, "WARNING")

def is_critical(tool_name: str) -> bool:
    return get_risk(tool_name) == "CRITICAL"
