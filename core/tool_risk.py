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
    "run_terminal_command":     "CRITICAL",
    "github_manager":           "CRITICAL",
    "mail_manager":             "CRITICAL",
    "relay_local_payload":      "CRITICAL",  # messenger draft → send
    "execute_local_pipeline":   "CRITICAL",
    "post_to_linkedin":         "CRITICAL",

    # ── WARNING: writes / side-effects / money ───────────────────
    "drive_manager":            "WARNING",
    "save_to_memory":           "WARNING",
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
    "create_file_tool":         "WARNING",
    "write_custom_tool":        "WARNING",

    # ── SAFE: reads / queries / zero side-effects ────────────────
    "search_memory":            "SAFE",
    "retrieve_photo":           "SAFE",
    "read_local_file":          "SAFE",
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
    "run_code":                 "SAFE",
    "recipe_expert":            "SAFE",
    "log_meal":                 "SAFE",
    "control_spotify":          "SAFE",
    "generate_image_tool":      "SAFE",
    "archive_file":             "SAFE",
}

def get_risk(tool_name: str) -> str:
    """Επιστρέφει SAFE/WARNING/CRITICAL. Default: WARNING αν άγνωστο."""
    return TOOL_RISK.get(tool_name, "WARNING")

def is_critical(tool_name: str) -> bool:
    return get_risk(tool_name) == "CRITICAL"
