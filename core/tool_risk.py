# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Tool Risk Registry
# Κάθε tool έχει ένα risk level:
#   SAFE     → εκτελεί αμέσως, χωρίς logging
#   WARNING  → εκτελεί αμέσως, λογάρει
#   CRITICAL → σταματά, ζητά Telegram confirmation
# ================================================================

TOOL_RISK: dict[str, str] = {
    # ── CRITICAL: destructive / external send / irreversible ────
    "run_terminal_command":     "DYNAMIC",  # risk καθορίζεται από classify_command() στο approval.py
    "github_manager":           "CRITICAL",
    "mail_manager":             "CRITICAL",
    "execute_local_pipeline":   "CRITICAL",
    "post_to_linkedin":         "CRITICAL",
    "process_and_clear_linkedin_post": "CRITICAL",

    # ── WARNING: writes / side-effects / money ───────────────────
    "drive_manager":            "WARNING",
    "save_to_memory":           "SAFE",    # non-destructive, γίνεται αυτόματα
    "save_goal_tool":           "WARNING",
    "update_goal_status_tool":  "WARNING",
    "delete_from_memory":       "WARNING",
    "control_vacuum":           "WARNING",
    "manage_list":              "WARNING",
    "set_reminder":             "WARNING",
    "set_local_reminder":       "WARNING",
    "google_calendar_tool":     "WARNING",
    "google_tasks_tool":        "WARNING",
    "learn_routine":            "WARNING",
    "write_code":               "WARNING",
    "create_file_tool":         "SAFE",    # τοπικό outputs/, μη καταστροφικό
    "generate_excel":           "SAFE",    # τοπικό outputs/, μη καταστροφικό
    "generate_word_doc":        "SAFE",    # τοπικό outputs/, μη καταστροφικό
    "generate_pdf":             "SAFE",    # τοπικό outputs/, μη καταστροφικό
    "generate_csv":             "SAFE",    # τοπικό outputs/, μη καταστροφικό
    "write_custom_tool":        "WARNING",
    "update_pending_linkedin_post": "WARNING",
    "relay_local_payload":      "WARNING",  # writes Messenger draft only; send is execute_local_pipeline

    # ── SAFE: reads / queries / zero side-effects ────────────────
    "search_memory":            "SAFE",
    "retrieve_photo":           "SAFE",
    "read_local_file":          "WARNING",  # reads filesystem — restricted to allowed dirs
    "get_news":                 "SAFE",
    "get_weather_forecast":     "SAFE",
    "duckduckgo_search":        "SAFE",
    "browse_url":               "SAFE",
    "search_google_places":     "SAFE",
    "get_navigation_info":      "SAFE",
    "search_goldmall_offers":   "SAFE",
    "search_supermarket_prices":"SAFE",
    "search_flights":           "SAFE",
    "get_fit_summary":          "SAFE",
    "get_routines":             "SAFE",
    "get_current_location":     "SAFE",
    "run_code":                 "WARNING",  # εκτελεί Python subprocess
    "recipe_expert":            "SAFE",
    "log_meal":                 "WARNING",  # γράφει σε food_history.json
    "control_spotify":          "WARNING",  # side effects: play/pause/next/search
    "generate_image_tool":      "WARNING",  # γράφει file + external API call
    "archive_file":             "WARNING",  # γράφει στη μνήμη (ChromaDB + JSON)
    "repo_mapper":              "SAFE",     # read-only AST scan

    # ── Project Tools: code navigation & editing ────────────────
    "grant_project_access":     "CRITICAL", # permanent permission change
    "list_project_files":       "SAFE",     # read-only glob
    "grep_project_files":       "SAFE",     # read-only regex search
    "read_project_file":        "SAFE",     # read-only
    "edit_project_file":        "WARNING",  # patch; escalates to CRITICAL for core files (approval.py)
    "write_project_file":       "CRITICAL", # full rewrite
    "register_tool":            "CRITICAL", # τροποποιεί system.py + tool_risk.py
    "scan_receipt":            "WARNING",
    "text_stats":              "SAFE",
}

def get_risk(tool_name: str) -> str:
    """Επιστρέφει SAFE/WARNING/CRITICAL. Default: WARNING αν άγνωστο."""
    return TOOL_RISK.get(tool_name, "WARNING")

def is_critical(tool_name: str) -> bool:
    return get_risk(tool_name) == "CRITICAL"
