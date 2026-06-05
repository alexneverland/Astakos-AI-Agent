import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_commit_requests_route_to_git_agent():
    from core.capability_lookup import lookup_agent, reload_registry

    reload_registry()

    assert lookup_agent("Δες commit τελευταία") == "Git_Agent"
    assert lookup_agent("git log -n 5 --oneline") == "Git_Agent"


def test_dev_requests_still_route_to_dev_agent():
    from core.capability_lookup import lookup_agent, reload_registry

    reload_registry()

    assert lookup_agent("έχω bug σε python script") == "Dev_Agent"
    assert lookup_agent("φτιάξε νέο skill") == "Dev_Agent"
