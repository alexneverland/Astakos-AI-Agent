"""
Tests for register_tool safe-apply with rollback.

Verifies that the apply path in register_tool:
1. Successfully updates all three registration targets.
2. Rolls back all targets if validation fails before any write.
3. Rolls back already-written targets if a mid-apply write fails.
4. Dry-run never writes files (baseline, complements test_new_skills.py).
5. Existing duplicate/conflict detection still works.

Uses temporary copies only — never real project files.
No live Telegram, .env, credentials, databases, or network access.
"""
import json
import os
import stat
from unittest.mock import patch


def _make_fake_project(tmp_path):
    """Creates a fake project structure for register_tool testing."""
    skills = tmp_path / "astakos_skills"
    skills.mkdir()
    core = tmp_path / "core"
    core.mkdir()
    tools = tmp_path / "tools"
    tools.mkdir()

    (tools / "system.py").write_text(
        'from astakos_skills.register_tool import register_tool\n'
        'all_tools = [\n'
        '    register_tool,\n'
        ']\n',
        encoding="utf-8",
    )
    (core / "tool_risk.py").write_text(
        'TOOL_RISK = {\n'
        '    "register_tool": "CRITICAL",\n'
        '}\n\ndef get_risk(name): return TOOL_RISK.get(name, "WARNING")\n'
        'def is_critical(name): return get_risk(name) == "CRITICAL"\n',
        encoding="utf-8",
    )
    (core / "capability_registry.json").write_text(
        json.dumps(
            [{"name": "existing_tool", "agent": "Dev_Agent",
              "description": "...", "priority": 9, "triggers": ["x"]}],
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    return tmp_path


def _write_minimal_skill(path):
    path.write_text(
        "from langchain_core.tools import tool\n"
        "\n"
        "@tool\n"
        "def my_tool(value: str) -> str:\n"
        '    """Echo text."""\n'
        "    return value\n",
        encoding="utf-8",
    )


def _snapshot(proj):
    """Capture raw bytes of all three registration targets."""
    return {
        "system": (proj / "tools" / "system.py").read_bytes(),
        "risk": (proj / "core" / "tool_risk.py").read_bytes(),
        "registry": (proj / "core" / "capability_registry.json").read_bytes(),
    }


# ── 1. Successful apply updates all three targets ──

def test_safe_apply_updates_all_three_targets(tmp_path):
    """After a successful apply, system.py, tool_risk.py, and registry are all changed."""
    from astakos_skills.register_tool import register_tool

    proj = _make_fake_project(tmp_path)
    _write_minimal_skill(proj / "astakos_skills" / "my_tool.py")
    before = _snapshot(proj)

    with patch("config.BASE_DIR", str(proj)):
        result = register_tool.func(
            tool_name="my_tool",
            description="Test tool",
            agent="Home_Agent",
            risk="SAFE",
            triggers="test trigger",
            dry_run=False,
        )

    assert "✅" in result
    after = _snapshot(proj)

    # All three must have changed
    assert after["system"] != before["system"], "system.py should have changed"
    assert after["risk"] != before["risk"], "tool_risk.py should have changed"
    assert after["registry"] != before["registry"], "registry should have changed"

    # Verify content correctness
    sys_text = after["system"].decode("utf-8")
    assert "from astakos_skills.my_tool import my_tool" in sys_text
    assert "    my_tool," in sys_text

    risk_text = after["risk"].decode("utf-8")
    assert '"my_tool"' in risk_text
    assert '"SAFE"' in risk_text

    registry = json.loads(after["registry"])
    names = [e["name"] for e in registry]
    assert "my_tool" in names


# ── 2. Validation failure before any write → no files changed ──

def test_validation_failure_changes_nothing(tmp_path):
    """If _safe_apply_all validation rejects content, no files are touched."""
    from astakos_skills.register_tool import _safe_apply_all

    proj = _make_fake_project(tmp_path)
    risk_path = str(proj / "core" / "tool_risk.py")
    sys_path = str(proj / "tools" / "system.py")
    registry_path = str(proj / "core" / "capability_registry.json")

    before = _snapshot(proj)

    # Propose syntactically invalid Python for tool_risk.py
    bad_python = b"TOOL_RISK = {\n    this is not valid python\n"
    good_json = (proj / "core" / "capability_registry.json").read_bytes()
    good_sys = (proj / "tools" / "system.py").read_bytes()

    error = _safe_apply_all([
        (risk_path, before["risk"], bad_python),
        (registry_path, before["registry"], good_json),
        (sys_path, before["system"], good_sys),
    ])

    assert error is not None
    assert "syntax error" in error.lower() or "validation failed" in error.lower()

    # All files must be unchanged
    after = _snapshot(proj)
    assert after == before, "No files should have changed after validation failure"


def test_invalid_utf8_validation_changes_nothing(tmp_path):
    """Invalid UTF-8 is rejected before any target is written."""
    from astakos_skills.register_tool import _safe_apply_all

    proj = _make_fake_project(tmp_path)
    risk_path = str(proj / "core" / "tool_risk.py")
    before = _snapshot(proj)

    error = _safe_apply_all([
        (risk_path, before["risk"], b"\xff\xfe"),
    ])

    assert error is not None
    assert "decode" in error.lower() or "utf-8" in error.lower()
    assert _snapshot(proj) == before


def test_safe_apply_preserves_target_mode(tmp_path):
    """Replacing a target keeps its original permission mode."""
    from astakos_skills.register_tool import _safe_apply_all

    proj = _make_fake_project(tmp_path)
    risk_path = proj / "core" / "tool_risk.py"
    before = risk_path.read_bytes()
    original_mode = stat.S_IMODE(risk_path.stat().st_mode)

    error = _safe_apply_all([
        (str(risk_path), before, before + b"\n# changed\n"),
    ])

    assert error is None
    assert stat.S_IMODE(risk_path.stat().st_mode) == original_mode


# ── 3. Mid-apply failure → rollback restores already-written targets ──

def test_mid_apply_failure_rolls_back(tmp_path):
    """If the third write fails, the first two are restored from originals."""
    from astakos_skills.register_tool import _safe_apply_all

    proj = _make_fake_project(tmp_path)
    risk_path = str(proj / "core" / "tool_risk.py")
    registry_path = str(proj / "core" / "capability_registry.json")
    sys_path = str(proj / "tools" / "system.py")

    before = _snapshot(proj)

    new_risk = before["risk"] + b"\n# changed\n"
    new_registry = before["registry"] + b"\n"
    new_sys = before["system"] + b"\n# changed\n"

    real_replace = os.replace
    failed = False

    def fail_once_for_system(source, destination):
        nonlocal failed
        if os.path.normcase(destination) == os.path.normcase(sys_path) and not failed:
            failed = True
            raise OSError("simulated system.py replacement failure")
        real_replace(source, destination)

    with patch("astakos_skills.register_tool.os.replace", side_effect=fail_once_for_system):
        error = _safe_apply_all([
            (risk_path, before["risk"], new_risk),
            (registry_path, before["registry"], new_registry),
            (sys_path, before["system"], new_sys),
        ])

    assert error is not None
    assert "rolled back" in error.lower()

    after = _snapshot(proj)
    assert after == before


# ── 4. Dry-run does not write files ──

def test_dry_run_does_not_write_files(tmp_path):
    """dry_run=True must not change any file on disk."""
    from astakos_skills.register_tool import register_tool

    proj = _make_fake_project(tmp_path)
    _write_minimal_skill(proj / "astakos_skills" / "my_tool.py")
    before = _snapshot(proj)

    with patch("config.BASE_DIR", str(proj)):
        result = register_tool.func(
            tool_name="my_tool",
            description="Test tool",
            agent="Home_Agent",
            risk="SAFE",
            triggers="test trigger",
            dry_run=True,
        )

    assert "DRY RUN" in result
    from core.i18n import t
    assert t("skills.register_tool.dry_run_footer") in result

    after = _snapshot(proj)
    assert after == before, "Dry-run must not change any file"


# ── 5. Duplicate/conflict detection still works ──

def test_duplicate_registration_still_detected(tmp_path):
    """A second register_tool call detects existing entries and is idempotent."""
    from astakos_skills.register_tool import register_tool

    proj = _make_fake_project(tmp_path)
    _write_minimal_skill(proj / "astakos_skills" / "my_tool.py")

    with patch("config.BASE_DIR", str(proj)):
        register_tool.func(tool_name="my_tool", risk="WARNING")
        before_second_apply = _snapshot(proj)
        result2 = register_tool.func(tool_name="my_tool", risk="WARNING")

    assert "already exists" in result2
    assert _snapshot(proj) == before_second_apply

    # No duplicates in registry
    registry = json.loads((proj / "core" / "capability_registry.json").read_text(encoding="utf-8"))
    assert len([e for e in registry if e["name"] == "my_tool"]) == 1


def test_apply_preserves_unchanged_target_bytes(tmp_path):
    """Applying a missing system entry does not rewrite existing registrations."""
    from astakos_skills.register_tool import register_tool

    proj = _make_fake_project(tmp_path)
    _write_minimal_skill(proj / "astakos_skills" / "my_tool.py")
    risk_path = proj / "core" / "tool_risk.py"
    registry_path = proj / "core" / "capability_registry.json"
    risk_path.write_bytes(
        b'TOOL_RISK = {\r\n'
        b'    "register_tool": "CRITICAL",\r\n'
        b'    "my_tool": "WARNING",\r\n'
        b'}\r\n\r\ndef get_risk(name): return TOOL_RISK.get(name, "WARNING")\r\n'
    )
    registry_path.write_bytes(
        b'[\r\n  {"name": "my_tool", "agent": "Dev_Agent"}\r\n]\r\n'
    )
    before = _snapshot(proj)

    with patch("config.BASE_DIR", str(proj)):
        result = register_tool.func(tool_name="my_tool", risk="WARNING")

    assert "system.py: import added" in result
    after = _snapshot(proj)
    assert after["system"] != before["system"]
    assert after["risk"] == before["risk"]
    assert after["registry"] == before["registry"]


# ── 6. Invalid JSON in proposed registry content → no files changed ──

def test_invalid_json_proposal_changes_nothing(tmp_path):
    """If proposed JSON content is invalid, _safe_apply_all rejects it pre-write."""
    from astakos_skills.register_tool import _safe_apply_all

    proj = _make_fake_project(tmp_path)
    registry_path = str(proj / "core" / "capability_registry.json")
    before = _snapshot(proj)

    bad_json = b"{ this is not json }"

    error = _safe_apply_all([
        (registry_path, before["registry"], bad_json),
    ])

    assert error is not None
    assert "invalid json" in error.lower()

    after = _snapshot(proj)
    assert after == before
