import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_commit_requests_route_to_git_agent():
    from core.capability_lookup import lookup_agent, reload_registry

    reload_registry()

    assert lookup_agent("Δες commit τελευταία") == "Git_Agent"
    assert lookup_agent("git log -n 5 --oneline") == "Git_Agent"


def test_logistics_profile_does_not_route_to_git_agent():
    from core.capability_lookup import lookup_agent, reload_registry

    reload_registry()

    assert lookup_agent("Lazaros works as Orders and Logistics Manager at Passias S.A.") != "Git_Agent"


def test_dev_requests_still_route_to_dev_agent():
    from core.capability_lookup import lookup_agent, reload_registry

    reload_registry()

    assert lookup_agent("έχω bug σε python script") == "Dev_Agent"
    assert lookup_agent("φτιάξε νέο skill") == "Dev_Agent"


def test_place_search_queries_route_to_web_agent():
    from core.capability_lookup import lookup_agent, reload_registry

    reload_registry()

    assert lookup_agent("βρες μου ήσυχο μέρος για φαγητό με παιδιά") == "Web_Agent"
    assert lookup_agent("δώσε μου 3 καλές ψαροταβέρνες κοντά στη Νέα Καλλικράτεια") == "Web_Agent"
    assert lookup_agent("Ψάξε git log για τα τελευταία commits.") == "Git_Agent"
    assert lookup_agent("Άνοιξε links για Python.") == "Dev_Agent"


def test_explicit_web_search_overrides_vacuum_capability():
    from core.capability_lookup import lookup_agent, reload_registry

    reload_registry()

    assert lookup_agent(
        "Ψάξε στο web για robot vacuum με πηγές."
    ) == "Web_Agent"


def test_explicit_web_search_overrides_dev_capability():
    from core.capability_lookup import lookup_agent, reload_registry

    reload_registry()

    assert lookup_agent(
        "Ψάξε στο web για Python με πηγές."
    ) == "Web_Agent"


def test_subject_capability_still_wins_without_explicit_web_search():
    from core.capability_lookup import lookup_agent, reload_registry

    reload_registry()

    assert lookup_agent(
        "Κάνε σύντομη έρευνα για robot vacuum."
    ) == "Home_Agent"
    assert lookup_agent(
        "Ψάξε για robot vacuum στο web."
    ) == "Home_Agent"


def test_clear_draft_is_not_routed_to_vacuum_capability() -> None:
    """A draft-cleanup command must not use the vacuum capability's generic trigger."""
    from core.capability_lookup import lookup_agent, reload_registry

    reload_registry()
    assert lookup_agent("Καθάρισε draft") != "Home_Agent"


def test_explicit_web_search_overrides_git_capability():
    from core.capability_lookup import lookup_agent, reload_registry

    reload_registry()

    assert lookup_agent(
        "Ψάξε στο web για git log με παραδείγματα."
    ) == "Web_Agent"


def test_unaccented_explicit_web_search_overrides_dev_capability():
    from core.capability_lookup import lookup_agent, reload_registry

    reload_registry()

    assert lookup_agent(
        "ψαξε στο web για Python με πηγές."
    ) == "Web_Agent"


def test_malformed_routing_override_triggers_are_ignored(monkeypatch):
    import core.capability_lookup as capability_lookup

    for malformed_value, user_message in (
        (None, "unmatched request"),
        ("-", "-"),
    ):
        monkeypatch.setattr(
            capability_lookup,
            "_registry",
            [
                {
                    "name": "web_search",
                    "agent": "Web_Agent",
                    "routing_override_triggers": malformed_value,
                    "triggers": [],
                }
            ],
        )

        assert capability_lookup.lookup_agent(user_message) is None


def test_explicit_web_search_without_article_overrides_price_capability() -> None:
    """Natural 'search web' wording must beat the generic price trigger."""
    from core.capability_lookup import lookup_agent, reload_registry

    reload_registry()

    assert lookup_agent(
        "Μπορείς να ψάξεις web στο Public και να μου πεις τιμή από καρέκλα γραφείου;"
    ) == "Web_Agent"


def test_specific_web_domain_overrides_price_capability() -> None:
    """A supplied website domain must use general Web search, not supermarket prices."""
    from core.capability_lookup import lookup_agent, reload_registry

    reload_registry()

    assert lookup_agent(
        "Βρες μου τιμή για καρέκλα γραφείου στο public.gr"
    ) == "Web_Agent"
