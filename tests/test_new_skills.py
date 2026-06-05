"""
Tests για τα νέα skills: repo_mapper + register_tool.
Τρέξε: pytest tests/test_new_skills.py -v
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
    """Σκανάρει ένα temp folder με .py αρχεία."""
    from astakos_skills.repo_mapper import repo_mapper

    # Δημιουργία test structure
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
    assert "deep.py" not in result  # depth=2 δεν φτάνει σε a/b/c


def test_repo_mapper_json_output(tmp_path):
    from astakos_skills.repo_mapper import repo_mapper

    (tmp_path / "mod.py").write_text(
        "class Foo: pass\ndef bar(): pass\n", encoding="utf-8"
    )
    result = repo_mapper.func(folder_path=str(tmp_path), max_depth=2)

    assert "```json" in result
    # Εξαγωγή JSON block
    json_part = result.split("```json")[1].split("```")[0].strip()
    data = json.loads(json_part)
    assert "mod.py" in data
    assert "Foo" in data["mod.py"]["classes"]
    assert "bar" in data["mod.py"]["functions"]


def test_repo_mapper_max_depth_clamped(tmp_path):
    from astakos_skills.repo_mapper import repo_mapper
    (tmp_path / "f.py").write_text("x=1\n", encoding="utf-8")
    # max_depth=99 πρέπει να γίνει clamp στο 6
    result = repo_mapper.func(folder_path=str(tmp_path), max_depth=99)
    assert "❌" not in result


# ═══════════════════════════════════════════════════════════════
# register_tool tests
# ═══════════════════════════════════════════════════════════════

def _make_fake_project(tmp_path):
    """Δημιουργεί fake project structure για test."""
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


def test_register_tool_dry_run_does_not_modify_files(tmp_path):
    from astakos_skills.register_tool import register_tool
    proj = _make_fake_project(tmp_path)
    (proj / "astakos_skills" / "my_tool.py").write_text("x=1", encoding="utf-8")

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
    assert "No files were changed" in result
    assert sys_path.read_text(encoding="utf-8") == before["system"]
    assert risk_path.read_text(encoding="utf-8") == before["risk"]
    assert registry_path.read_text(encoding="utf-8") == before["registry"]


def test_register_tool_full_registration(tmp_path):
    from astakos_skills.register_tool import register_tool
    proj = _make_fake_project(tmp_path)

    # Δημιουργία του skill αρχείου
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
    """Δεύτερη κλήση δεν κάνει διπλοεγγραφή."""
    from astakos_skills.register_tool import register_tool
    proj = _make_fake_project(tmp_path)
    (proj / "astakos_skills" / "my_tool.py").write_text("x=1", encoding="utf-8")

    with patch("config.BASE_DIR", str(proj)):
        register_tool.func(tool_name="my_tool", risk="WARNING")
        result2 = register_tool.func(tool_name="my_tool", risk="WARNING")

    assert "ήδη υπάρχει" in result2

    # Verify no duplicates in registry
    registry = json.loads((proj / "core" / "capability_registry.json").read_text(encoding="utf-8"))
    assert len([e for e in registry if e["name"] == "my_tool"]) == 1
