from core.capability_lookup import lookup_agent


def test_get_world_time_routing_ignores_generic_phrases() -> None:
    """Keep generic calendar and code questions out of world-time routing."""
    # "What time is my calendar meeting?" does NOT route through get_world_time.
    assert lookup_agent("What time is my calendar meeting?") != "Chat_Agent"
    # "What is the time complexity of this code?" does NOT route through get_world_time.
    assert lookup_agent("What is the time complexity of this code?") != "Chat_Agent"

def test_get_world_time_routing_matches_specific_phrases() -> None:
    """Route explicit English and Greek world-time questions to Chat_Agent."""
    # "What time is it in London?" routes to Chat_Agent.
    assert lookup_agent("What time is it in London?") == "Chat_Agent"
    # "Τι ώρα είναι στο Λονδίνο;" routes to Chat_Agent.
    assert lookup_agent("Τι ώρα είναι στο Λονδίνο;") == "Chat_Agent"
