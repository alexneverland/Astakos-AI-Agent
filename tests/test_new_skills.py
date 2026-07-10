"""
Tests for the new skills: repo_mapper + register_tool.
Run: pytest tests/test_new_skills.py -v
"""
import sys, os, json, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch


# ═══════════════════════════════════════════════════════════════
# repo_mapper tests
# ═══════════════════════════════════════════════════════════════

def test_repo_mapper_invalid_folder():
    from astakos_skills.repo_mapper import repo_mapper
    result = repo_mapper.func(folder_path="C:\\nonexistent\\path\\xyz")
    assert "❌" in result


def test_repo_mapper_valid_folder(tmp_path):
    """Scans a temp folder with .py files."""
    from astakos_skills.repo_mapper import repo_mapper

    # Create test structure
    (tmp_path / "main.py").write_text(
        "def hello(): pass\nclass MyClass: pass\n", encoding="utf-8"
    )
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "util.py").write_text(
        "def helper(): pass\n", encoding="utf-8"
    )
    (tmp_path / "ignore.pyc").write_bytes(b"bytecode")

    result = repo_mapper.func(folder_path=str(tmp_path), max_depth=3)

    assert "main.py" in result
    assert "hello" in result
    assert "MyClass" in result
    assert "util.py" in result
    assert "ignore.pyc" not in result  # skip extension


def test_repo_mapper_skips_venv(tmp_path):
    from astakos_skills.repo_mapper import repo_mapper

    (tmp_path / "app.py").write_text("def run(): pass\n", encoding="utf-8")
    venv = tmp_path / "venv"
    venv.mkdir()
    (venv / "secret.py").write_text("API_KEY='abc'\n", encoding="utf-8")

    result = repo_mapper.func(folder_path=str(tmp_path), max_depth=3)

    assert "app.py" in result
    assert "secret.py" not in result  # venv skipped


def test_repo_mapper_depth_limit(tmp_path):
    from astakos_skills.repo_mapper import repo_mapper

    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "deep.py").write_text("x = 1\n", encoding="utf-8")

    result = repo_mapper.func(folder_path=str(tmp_path), max_depth=2)
    assert "deep.py" not in result  # depth=2 is not enough to reach a/b/c


def test_repo_mapper_json_output(tmp_path):
    from astakos_skills.repo_mapper import repo_mapper

    (tmp_path / "mod.py").write_text(
        "class Foo: pass\ndef bar(): pass\n", encoding="utf-8"
    )
    result = repo_mapper.func(folder_path=str(tmp_path), max_depth=2)

    assert "```json" in result
    # JSON block extraction
    json_part = result.split("```json")[1].split("```")[0].strip()
    data = json.loads(json_part)
    assert "mod.py" in data
    assert "Foo" in data["mod.py"]["classes"]
    assert "bar" in data["mod.py"]["functions"]


def test_repo_mapper_max_depth_clamped(tmp_path):
    from astakos_skills.repo_mapper import repo_mapper
    (tmp_path / "f.py").write_text("x=1\n", encoding="utf-8")
    # max_depth=99 must be clamped to 6
    result = repo_mapper.func(folder_path=str(tmp_path), max_depth=99)
    assert "❌" not in result


# ═══════════════════════════════════════════════════════════════
# register_tool tests
# ═══════════════════════════════════════════════════════════════

def _make_fake_project(tmp_path):
    """Creates a fake project structure for testing."""
    skills = tmp_path / "astakos_skills"
    skills.mkdir()
    core = tmp_path / "core"
    core.mkdir()
    tools = tmp_path / "tools"
    tools.mkdir()

    # Fake system.py
    (tools / "system.py").write_text(
        'from astakos_skills.register_tool import register_tool\n'
        'all_tools = [\n'
        '    register_tool,\n'
        ']\n',
        encoding="utf-8"
    )

    # Fake tool_risk.py
    (core / "tool_risk.py").write_text(
        'TOOL_RISK = {\n'
        '    "register_tool": "CRITICAL",\n'
        '}\n\ndef get_risk(name): return TOOL_RISK.get(name, "WARNING")\n'
        'def is_critical(name): return get_risk(name) == "CRITICAL"\n',
        encoding="utf-8"
    )

    # Fake capability_registry.json
    (core / "capability_registry.json").write_text(
        json.dumps([{"name": "existing_tool", "agent": "Dev_Agent",
                     "description": "...", "priority": 9, "triggers": ["x"]}],
                   ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    return tmp_path


def _write_minimal_skill(path):
    path.write_text(
        "from langchain_core.tools import tool\n"
        "\n"
        "@tool\n"
        "def my_tool(value: str) -> str:\n"
        "    \"\"\"Echo text.\"\"\"\n"
        "    return value\n",
        encoding="utf-8",
    )


def test_register_tool_missing_skill_file(tmp_path):
    from astakos_skills.register_tool import register_tool
    proj = _make_fake_project(tmp_path)

    with patch("config.BASE_DIR", str(proj)):
        result = register_tool.func(
            tool_name="nonexistent_tool",
            agent="Dev_Agent", risk="WARNING"
        )
    assert "❌" in result
    assert "nonexistent_tool.py" in result


def test_register_tool_invalid_risk(tmp_path):
    from astakos_skills.register_tool import register_tool
    proj = _make_fake_project(tmp_path)
    (proj / "astakos_skills" / "my_tool.py").write_text("x=1", encoding="utf-8")

    with patch("config.BASE_DIR", str(proj)):
        result = register_tool.func(
            tool_name="my_tool",
            agent="Dev_Agent", risk="INVALID"
        )
    assert "❌" in result
    assert "INVALID" in result


def test_register_tool_rejects_invalid_tool_name(tmp_path):
    from astakos_skills.register_tool import register_tool
    proj = _make_fake_project(tmp_path)

    with patch("config.BASE_DIR", str(proj)):
        result = register_tool.func(
            tool_name="../bad_tool",
            agent="Dev_Agent",
            risk="WARNING",
        )

    assert "invalid tool_name" in result


def test_register_tool_rejects_skill_without_tool_decorator(tmp_path):
    from astakos_skills.register_tool import register_tool
    proj = _make_fake_project(tmp_path)
    (proj / "astakos_skills" / "my_tool.py").write_text(
        "def my_tool(value: str) -> str:\n"
        "    return value\n",
        encoding="utf-8",
    )

    with patch("config.BASE_DIR", str(proj)):
        result = register_tool.func(
            tool_name="my_tool",
            agent="Dev_Agent",
            risk="WARNING",
            dry_run=True,
        )

    assert "not a valid tool skill" in result
    assert "must have @tool" in result
    assert "No files were changed" in result


def test_register_tool_dry_run_does_not_modify_files(tmp_path):
    from astakos_skills.register_tool import register_tool
    proj = _make_fake_project(tmp_path)
    _write_minimal_skill(proj / "astakos_skills" / "my_tool.py")

    sys_path = proj / "tools" / "system.py"
    risk_path = proj / "core" / "tool_risk.py"
    registry_path = proj / "core" / "capability_registry.json"
    before = {
        "system": sys_path.read_text(encoding="utf-8"),
        "risk": risk_path.read_text(encoding="utf-8"),
        "registry": registry_path.read_text(encoding="utf-8"),
    }

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
    assert "DIFF PREVIEW" in result
    assert "--- a/tools/system.py" in result
    assert "--- a/core/tool_risk.py" in result
    assert "--- a/core/capability_registry.json" in result
    assert "No files were changed" in result
    assert sys_path.read_text(encoding="utf-8") == before["system"]
    assert risk_path.read_text(encoding="utf-8") == before["risk"]
    assert registry_path.read_text(encoding="utf-8") == before["registry"]


def test_tool_creation_end_to_end_write_dry_run_apply_registers_everywhere(tmp_path, monkeypatch):
    import tools.system as system
    from astakos_skills.register_tool import register_tool

    proj = _make_fake_project(tmp_path)
    skill_dir = proj / "astakos_skills"
    monkeypatch.setattr(system, "WORKSPACE_DIR", str(skill_dir))

    tool_code = '''
from langchain_core.tools import tool

@tool
def my_tool(value: str) -> str:
    """Uppercase text."""
    return value.upper()
'''

    created = system.write_custom_tool.func("my_tool", tool_code)

    assert "Tool 'my_tool'" in created
    assert "TEST_OK: TEST" in created
    assert (skill_dir / "my_tool.py").exists()

    sys_path = proj / "tools" / "system.py"
    risk_path = proj / "core" / "tool_risk.py"
    registry_path = proj / "core" / "capability_registry.json"
    before = {
        "system": sys_path.read_text(encoding="utf-8"),
        "risk": risk_path.read_text(encoding="utf-8"),
        "registry": registry_path.read_text(encoding="utf-8"),
    }

    with patch("config.BASE_DIR", str(proj)):
        dry = register_tool.func(
            tool_name="my_tool",
            description="Uppercase text",
            agent="Chat_Agent",
            risk="SAFE",
            triggers="uppercase, κεφαλαία",
            dry_run=True,
        )

    assert "DRY RUN" in dry
    assert "DIFF PREVIEW" in dry
    assert sys_path.read_text(encoding="utf-8") == before["system"]
    assert risk_path.read_text(encoding="utf-8") == before["risk"]
    assert registry_path.read_text(encoding="utf-8") == before["registry"]

    with patch("config.BASE_DIR", str(proj)):
        applied = register_tool.func(
            tool_name="my_tool",
            description="Uppercase text",
            agent="Chat_Agent",
            risk="SAFE",
            triggers="uppercase, κεφαλαία",
            dry_run=False,
        )

    assert "my_tool" in applied
    assert "DRY RUN" not in applied
    assert "from astakos_skills.my_tool import my_tool" in sys_path.read_text(encoding="utf-8")
    assert "    my_tool," in sys_path.read_text(encoding="utf-8")

    risk_content = risk_path.read_text(encoding="utf-8")
    assert '"my_tool"' in risk_content
    assert '"SAFE"' in risk_content

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    entry = next(item for item in registry if item["name"] == "my_tool")
    assert entry["agent"] == "Chat_Agent"
    assert entry["description"] == "Uppercase text"
    assert entry["triggers"] == ["uppercase", "κεφαλαία"]


def test_register_tool_missing_anchors_do_not_partially_write(tmp_path):
    from astakos_skills.register_tool import register_tool
    proj = _make_fake_project(tmp_path)
    _write_minimal_skill(proj / "astakos_skills" / "my_tool.py")

    sys_path = proj / "tools" / "system.py"
    risk_path = proj / "core" / "tool_risk.py"
    registry_path = proj / "core" / "capability_registry.json"
    sys_path.write_text("all_tools = []\n", encoding="utf-8")
    before = {
        "system": sys_path.read_text(encoding="utf-8"),
        "risk": risk_path.read_text(encoding="utf-8"),
        "registry": registry_path.read_text(encoding="utf-8"),
    }

    with patch("config.BASE_DIR", str(proj)):
        result = register_tool.func(
            tool_name="my_tool",
            description="Test tool",
            agent="Home_Agent",
            risk="SAFE",
            triggers="test trigger",
            dry_run=False,
        )

    assert "Δεν εφαρμόστηκε τίποτα" in result
    assert "missing import anchor" in result
    assert "missing all_tools anchor" in result
    assert "No files were changed" in result
    assert sys_path.read_text(encoding="utf-8") == before["system"]
    assert risk_path.read_text(encoding="utf-8") == before["risk"]
    assert registry_path.read_text(encoding="utf-8") == before["registry"]


def test_register_tool_full_registration(tmp_path):
    from astakos_skills.register_tool import register_tool
    proj = _make_fake_project(tmp_path)

    # Creation of the skill file
    (proj / "astakos_skills" / "my_tool.py").write_text(
        "from langchain_core.tools import tool\n@tool\ndef my_tool(x: str) -> str: return x\n",
        encoding="utf-8"
    )

    with patch("config.BASE_DIR", str(proj)):
        result = register_tool.func(
            tool_name="my_tool",
            description="Test tool",
            agent="Home_Agent",
            risk="SAFE",
            triggers="test trigger, κάνε test"
        )

    assert "✅" in result
    assert "my_tool" in result

    # Verify system.py
    sys_content = (proj / "tools" / "system.py").read_text(encoding="utf-8")
    assert "from astakos_skills.my_tool import my_tool" in sys_content
    assert "    my_tool," in sys_content

    # Verify tool_risk.py
    risk_content = (proj / "core" / "tool_risk.py").read_text(encoding="utf-8")
    assert '"my_tool"' in risk_content
    assert '"SAFE"' in risk_content

    # Verify capability_registry.json
    registry = json.loads((proj / "core" / "capability_registry.json").read_text(encoding="utf-8"))
    names = [e["name"] for e in registry]
    assert "my_tool" in names
    entry = next(e for e in registry if e["name"] == "my_tool")
    assert entry["agent"] == "Home_Agent"
    assert "test trigger" in entry["triggers"]


def test_register_tool_idempotent(tmp_path):
    """A second call does not create a duplicate entry."""
    from astakos_skills.register_tool import register_tool
    proj = _make_fake_project(tmp_path)
    _write_minimal_skill(proj / "astakos_skills" / "my_tool.py")

    with patch("config.BASE_DIR", str(proj)):
        register_tool.func(tool_name="my_tool", risk="WARNING")
        result2 = register_tool.func(tool_name="my_tool", risk="WARNING")

    assert "ήδη υπάρχει" in result2

    # Verify no duplicates in registry
    registry = json.loads((proj / "core" / "capability_registry.json").read_text(encoding="utf-8"))
    assert len([e for e in registry if e["name"] == "my_tool"]) == 1
