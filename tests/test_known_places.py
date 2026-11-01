"""Named GPS places use canonical persistence, not a profile acknowledgement."""

import json
import time

import pytest


@pytest.fixture
def place_files(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "GPS_STORAGE_FILE", str(tmp_path / "gps.json"))
    monkeypatch.setattr(config, "HOME_COORDS", (40.646558, 22.939036))
    monkeypatch.setattr(config, "WORK_COORDS", (40.690914, 22.929607))
    monkeypatch.setattr(config, "HOME_RADIUS_M", 150)
    monkeypatch.setattr(config, "WORK_RADIUS_M", 300)
    return tmp_path


def write_point(root, *, age=0, lat=40.6449, lon=22.9364):
    (root / "gps.json").write_text(json.dumps({"lat": lat, "lon": lon,
        "timestamp": time.time()-age}), encoding="utf-8")


def test_save_and_locate_park_with_configured_home_and_work(place_files):
    from astakos_skills.known_places import manage_known_places
    write_point(place_files)
    result = json.loads(manage_known_places.invoke({"action": "save_current",
        "name": "Πάρκο Γεωργίου Ιβάνοφ"}))
    assert result["status"] == "saved"
    assert result["place"]["lat"] == 40.6449
    stored = json.loads((place_files / "known_places.json").read_text(encoding="utf-8"))
    assert stored["places"][0]["name"] == "Πάρκο Γεωργίου Ιβάνοφ"
    listed = json.loads(manage_known_places.invoke({"action": "list"}))
    assert {p["name"] for p in listed["places"]} == {"home", "work", "Πάρκο Γεωργίου Ιβάνοφ"}
    located = json.loads(manage_known_places.invoke({"action": "locate"}))
    assert located["matches"][0]["name"] == "Πάρκο Γεωργίου Ιβάνοφ"
    assert located["matches"][0]["distance_m"] < 1


@pytest.mark.parametrize("age", [601, -30])
def test_stale_or_future_gps_cannot_save_or_locate(place_files, age):
    from astakos_skills.known_places import manage_known_places
    write_point(place_files, age=age)
    for action in ("save_current", "locate"):
        result = json.loads(manage_known_places.invoke({"action": action, "name": "Park"}))
        assert result["status"] == "unavailable"
    assert not (place_files / "known_places.json").exists()


def test_corrupt_store_is_preserved_and_never_claims_save(place_files):
    from astakos_skills.known_places import manage_known_places
    write_point(place_files)
    store = place_files / "known_places.json"
    store.write_text('{"broken":true}', encoding="utf-8")
    result = json.loads(manage_known_places.invoke({"action": "save_current", "name": "Park"}))
    assert result["status"] == "error"
    assert store.read_text(encoding="utf-8") == '{"broken":true}'


def test_configured_places_cannot_be_overwritten(place_files):
    from astakos_skills.known_places import manage_known_places
    write_point(place_files)
    result = json.loads(manage_known_places.invoke({"action": "save_current", "name": "home"}))
    assert result["status"] == "error"
    assert not (place_files / "known_places.json").exists()


def test_local_save_retains_external_content_mutation_gate(place_files):
    from core.untrusted_content import is_read_only_external_followup_tool
    assert not is_read_only_external_followup_tool("manage_known_places", {"action": "save_current"})
    assert is_read_only_external_followup_tool("manage_known_places", {"action": "list"})
    assert is_read_only_external_followup_tool("manage_known_places", {"action": "locate"})


def test_registered_home_tool_executes_real_toolnode_and_persists(place_files, monkeypatch):
    """Only the model selection is supplied; the binding and file write are real."""
    from pathlib import Path
    from langchain_core.messages import AIMessage
    from langgraph.prebuilt import ToolNode
    from langgraph.graph import END, START, MessagesState, StateGraph
    from core import agent_tools
    from astakos_skills.known_places import manage_known_places
    monkeypatch.setattr(agent_tools, "_load_trusted_all_tools", lambda: [manage_known_places])
    monkeypatch.setattr(agent_tools, "_registry_path",
        lambda: str(Path(__file__).resolve().parents[1] / "core/capability_registry.json"))
    tools = agent_tools.get_registered_tools_for_agent("Home_Agent", [])
    assert tools == [manage_known_places]
    write_point(place_files)
    workflow = StateGraph(MessagesState)
    workflow.add_node("tools", ToolNode(tools))
    workflow.add_edge(START, "tools")
    workflow.add_edge("tools", END)
    result = workflow.compile().invoke({"messages": [AIMessage(content="", tool_calls=[{
        "id": "save-park", "name": "manage_known_places",
        "args": {"action": "save_current", "name": "Πάρκο Γεωργίου Ιβάνοφ"}}])]})
    assert json.loads(result["messages"][-1].content)["status"] == "saved"
    assert json.loads((place_files / "known_places.json").read_text(encoding="utf-8"))["places"][0]["lat"] == 40.6449


def test_failed_write_never_claims_saved_or_replaces_existing_place(place_files, monkeypatch):
    from astakos_skills.known_places import manage_known_places
    from memory import known_places
    write_point(place_files)
    assert json.loads(manage_known_places.invoke({"action": "save_current", "name": "First"}))["status"] == "saved"
    before = (place_files / "known_places.json").read_bytes()
    def fail_replace(*args):
        raise OSError("injected replace failure")
    monkeypatch.setattr(known_places.os, "replace", fail_replace)
    assert json.loads(manage_known_places.invoke({"action": "save_current", "name": "Second"}))["status"] == "error"
    assert (place_files / "known_places.json").read_bytes() == before


def test_concurrent_place_saves_preserve_both_names(place_files):
    from concurrent.futures import ThreadPoolExecutor
    from memory.known_places import save_current_place, list_known_places
    write_point(place_files)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(pool.map(save_current_place, ["First", "Second"]))
    assert {p["name"] for p in list_known_places()} == {"home", "work", "First", "Second"}
