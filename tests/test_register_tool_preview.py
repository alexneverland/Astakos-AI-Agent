import os

import pytest


@pytest.mark.parametrize("fail_output_dir", [False, True])
def test_register_tool_preview_artifact(tmp_path, monkeypatch, fail_output_dir):
    import astakos_skills.register_tool as rt
    import config

    import shutil

    # Mock BASE_DIR to our tmp_path
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))

    # Copy locales to tmp_path so translations load properly
    shutil.copytree(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locales"), tmp_path / "locales")

    # Create the necessary folder structure in the tmp_path
    skills_dir = tmp_path / "astakos_skills"
    tools_dir = tmp_path / "tools"
    core_dir = tmp_path / "core"

    skills_dir.mkdir()
    tools_dir.mkdir()
    core_dir.mkdir()

    # Create a dummy skill to register
    dummy_skill = skills_dir / "dummy_preview_tool.py"
    dummy_skill.write_text("from langchain_core.tools import tool\n\n@tool\ndef dummy_preview_tool(): pass\n")

    # Create the files that would normally be modified
    system_py = tools_dir / "system.py"
    system_py.write_text("from astakos_skills.register_tool import register_tool\nall_tools = [\n]\n")

    tool_risk_py = core_dir / "tool_risk.py"
    tool_risk_py.write_text("TOOL_RISK_REGISTRY = {}\n\ndef get_risk(name: str) -> str:\n    return 'SAFE'\n")

    cap_reg = core_dir / "capability_registry.json"
    cap_reg.write_text("[]")

    # Capture original contents and mtimes
    orig_system = system_py.read_text()
    orig_risk = tool_risk_py.read_text()
    orig_cap = cap_reg.read_text()

    system_mtime = system_py.stat().st_mtime
    risk_mtime = tool_risk_py.stat().st_mtime
    cap_mtime = cap_reg.stat().st_mtime

    if fail_output_dir:
        def raise_output_directory_error(*_args, **_kwargs):
            raise OSError("output directory unavailable")

        monkeypatch.setattr(rt.os, "makedirs", raise_output_directory_error)

    # Run register_tool in dry_run mode
    res = rt.register_tool.func(tool_name="dummy_preview_tool", dry_run=True)

    # Assert dry run ran
    assert "DRY RUN" in res

    outputs_dir = tmp_path / "outputs"
    artifact = outputs_dir / "draft_diff_dummy_preview_tool.md"
    if fail_output_dir:
        assert "[WARN]" in res
        assert not artifact.exists()
    else:
        assert artifact.exists()
        assert "dummy_preview_tool" in artifact.read_text(encoding="utf-8")

    # Verify the actual target files were NOT modified (neither content nor timestamp)
    assert system_py.read_text() == orig_system
    assert tool_risk_py.read_text() == orig_risk
    assert cap_reg.read_text() == orig_cap

    assert system_py.stat().st_mtime == system_mtime
    assert tool_risk_py.stat().st_mtime == risk_mtime
    assert cap_reg.stat().st_mtime == cap_mtime
