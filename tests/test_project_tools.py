"""
Tests για tools/project_tools.py — permission model, read/edit/grep/list.
Τρεξε: python -m pytest tests/test_project_tools.py -v
"""
import sys, os, json, tempfile, textwrap
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest, tempfile, shutil
from unittest.mock import patch, MagicMock


# ── Helpers ──────────────────────────────────────────────────────
# Cross-platform temp dir. On Windows, /tmp does not necessarily exist.

@pytest.fixture
def tmp_path():
    """Override pytest tmp_path with a deterministic temporary folder."""
    import pathlib
    d = tempfile.mkdtemp(prefix="test_astakos_", dir=tempfile.gettempdir())
    yield pathlib.Path(d)
    shutil.rmtree(d, ignore_errors=True)


def _make_access_file(tmp_path, folder, read=True, edit=True):
    access_file = str(tmp_path / "project_access.json")
    data = {str(folder): {"read": read, "edit": edit, "label": "TestProject"}}
    with open(access_file, "w") as f:
        json.dump(data, f)
    return access_file


def _make_py_file(folder, name, content):
    path = os.path.join(str(folder), name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ── Permission checks ─────────────────────────────────────────────

def test_check_permission_granted(tmp_path):
    from tools.project_tools import _check_permission, _normalize
    access_file = _make_access_file(tmp_path, tmp_path)
    target = os.path.join(str(tmp_path), "views.py")
    with patch("tools.project_tools.PROJECT_ACCESS_FILE", access_file):
        ok, err = _check_permission(target, need_edit=False)
    assert ok, err


def test_check_permission_denied_no_grant(tmp_path):
    from tools.project_tools import _check_permission
    access_file = str(tmp_path / "project_access.json")
    with open(access_file, "w") as f:
        json.dump({}, f)
    target = os.path.join(str(tmp_path), "views.py")
    with patch("tools.project_tools.PROJECT_ACCESS_FILE", access_file):
        ok, err = _check_permission(target)
    assert not ok
    assert "grant_project_access" in err


def test_check_permission_read_only_blocks_edit(tmp_path):
    from tools.project_tools import _check_permission
    access_file = _make_access_file(tmp_path, tmp_path, read=True, edit=False)
    target = os.path.join(str(tmp_path), "views.py")
    with patch("tools.project_tools.PROJECT_ACCESS_FILE", access_file):
        ok, err = _check_permission(target, need_edit=True)
    assert not ok
    assert "read" in err.lower()


# ── Syntax check ──────────────────────────────────────────────────

def test_syntax_check_valid_python():
    from tools.project_tools import _syntax_check
    ok, err = _syntax_check("x = 1 + 2\n", "foo.py")
    assert ok


def test_syntax_check_invalid_python():
    from tools.project_tools import _syntax_check
    ok, err = _syntax_check("def foo(\n", "foo.py")
    assert not ok
    assert "SyntaxError" in err


def test_syntax_check_skips_non_python():
    from tools.project_tools import _syntax_check
    ok, err = _syntax_check("not python {{ invalid }}", "template.html")
    assert ok  # non-.py αρχεία δεν ελέγχονται


# ── read_project_file ─────────────────────────────────────────────

def test_read_project_file_returns_lines(tmp_path):
    from tools.project_tools import read_project_file
    access_file = _make_access_file(tmp_path, tmp_path)
    path = _make_py_file(tmp_path, "models.py", "class Foo:\n    pass\n")
    with patch("tools.project_tools.PROJECT_ACCESS_FILE", access_file):
        result = read_project_file.func(file_path=path)
    assert "class Foo" in result


def test_read_project_file_with_line_range(tmp_path):
    from tools.project_tools import read_project_file
    access_file = _make_access_file(tmp_path, tmp_path)
    content = "\n".join(f"line{i}" for i in range(1, 20))
    path = _make_py_file(tmp_path, "big.py", content)
    with patch("tools.project_tools.PROJECT_ACCESS_FILE", access_file):
        result = read_project_file.func(file_path=path, start_line=5, end_line=8)
    assert "line5" in result
    assert "line9" not in result


def test_read_project_file_no_permission(tmp_path):
    from tools.project_tools import read_project_file
    access_file = str(tmp_path / "project_access.json")
    with open(access_file, "w") as f:
        json.dump({}, f)
    path = _make_py_file(tmp_path, "views.py", "x=1")
    with patch("tools.project_tools.PROJECT_ACCESS_FILE", access_file):
        result = read_project_file.func(file_path=path)
    assert "❌" in result


# ── edit_project_file ─────────────────────────────────────────────

def test_edit_project_file_basic(tmp_path):
    from tools.project_tools import edit_project_file
    access_file = _make_access_file(tmp_path, tmp_path)
    path = _make_py_file(tmp_path, "views.py", "def get_queryset():\n    return Foo.objects.all()\n")
    with patch("tools.project_tools.PROJECT_ACCESS_FILE", access_file):
        result = edit_project_file.func(
            file_path=path,
            old_str="return Foo.objects.all()",
            new_str="return Foo.objects.filter(active=True)",
        )
    assert "✅" in result
    with open(path) as f:
        assert "filter(active=True)" in f.read()


def test_edit_project_file_noop_guard(tmp_path):
    from tools.project_tools import edit_project_file
    access_file = _make_access_file(tmp_path, tmp_path)
    path = _make_py_file(tmp_path, "views.py", "x = 1\n")
    with patch("tools.project_tools.PROJECT_ACCESS_FILE", access_file):
        result = edit_project_file.func(file_path=path, old_str="x = 1", new_str="x = 1")
    assert "no-op" in result.lower() or "ίδιο" in result or "πανομοιότυπα" in result


def test_edit_project_file_not_unique(tmp_path):
    from tools.project_tools import edit_project_file
    access_file = _make_access_file(tmp_path, tmp_path)
    path = _make_py_file(tmp_path, "views.py", "x = 1\nx = 1\n")
    with patch("tools.project_tools.PROJECT_ACCESS_FILE", access_file):
        result = edit_project_file.func(file_path=path, old_str="x = 1", new_str="x = 2")
    assert "❌" in result or "2 φορ" in result


def test_edit_project_file_syntax_check_catches_error(tmp_path):
    from tools.project_tools import edit_project_file
    access_file = _make_access_file(tmp_path, tmp_path)
    path = _make_py_file(tmp_path, "views.py", "def foo():\n    return 1\n")
    with patch("tools.project_tools.PROJECT_ACCESS_FILE", access_file):
        result = edit_project_file.func(
            file_path=path,
            old_str="return 1",
            new_str="return (1",  # broken syntax
        )
    assert "SyntaxError" in result or "❌" in result
    # Αρχείο δεν πρέπει να άλλαξε
    with open(path) as f:
        assert "return 1" in f.read()


# ── grep_project_files ────────────────────────────────────────────

def test_grep_project_files_finds_match(tmp_path):
    from tools.project_tools import grep_project_files
    access_file = _make_access_file(tmp_path, tmp_path)
    _make_py_file(tmp_path, "models.py", "class Customer(models.Model):\n    name = models.CharField()\n")
    with patch("tools.project_tools.PROJECT_ACCESS_FILE", access_file):
        result = grep_project_files.func(folder_path=str(tmp_path), pattern="class Customer")
    assert "Customer" in result
    assert "models.py" in result


def test_grep_project_files_no_match(tmp_path):
    from tools.project_tools import grep_project_files
    access_file = _make_access_file(tmp_path, tmp_path)
    _make_py_file(tmp_path, "views.py", "def index(): pass\n")
    with patch("tools.project_tools.PROJECT_ACCESS_FILE", access_file):
        result = grep_project_files.func(folder_path=str(tmp_path), pattern="NONEXISTENT_XYZ")
    assert "0" in result or "Κανένα" in result or "No match" in result.lower()


def test_grep_project_files_no_permission(tmp_path):
    from tools.project_tools import grep_project_files
    access_file = str(tmp_path / "project_access.json")
    with open(access_file, "w") as f:
        json.dump({}, f)
    with patch("tools.project_tools.PROJECT_ACCESS_FILE", access_file):
        result = grep_project_files.func(folder_path=str(tmp_path), pattern="anything")
    assert "❌" in result


# ── list_project_files ────────────────────────────────────────────

def test_list_project_files_returns_py_files(tmp_path):
    from tools.project_tools import list_project_files
    access_file = _make_access_file(tmp_path, tmp_path)
    _make_py_file(tmp_path, "models.py", "")
    _make_py_file(tmp_path, "views.py", "")
    with patch("tools.project_tools.PROJECT_ACCESS_FILE", access_file):
        result = list_project_files.func(folder_path=str(tmp_path), pattern="**/*.py")
    assert "models.py" in result
    assert "views.py" in result


# ── tool_risk για project tools ───────────────────────────────────

def test_grant_project_access_is_critical():
    from core.tool_risk import get_risk
    assert get_risk("grant_project_access") == "CRITICAL"

def test_list_project_files_is_safe():
    from core.tool_risk import get_risk
    assert get_risk("list_project_files") == "SAFE"

def test_read_project_file_is_safe():
    from core.tool_risk import get_risk
    assert get_risk("read_project_file") == "SAFE"

def test_grep_project_files_is_safe():
    from core.tool_risk import get_risk
    assert get_risk("grep_project_files") == "SAFE"

def test_write_project_file_is_critical():
    from core.tool_risk import get_risk
    assert get_risk("write_project_file") == "CRITICAL"

def test_edit_project_file_non_core_is_warning():
    from core.approval import _effective_risk
    tc = {"name": "edit_project_file", "args": {"file_path": "C:\\mastro_app\\api\\views.py"}, "id": "x"}
    assert _effective_risk(tc) == "WARNING"

def test_edit_project_file_core_is_critical():
    from core.approval import _effective_risk
    tc = {"name": "edit_project_file", "args": {"file_path": "C:\\astakos_v2\\core\\agents.py"}, "id": "x"}
    assert _effective_risk(tc) == "CRITICAL"


# ── grep_project_files in all_tools ──────────────────────────────

def test_grep_project_files_in_all_tools():
    """Ελέγχει ότι grep_project_files αναφέρεται στο all_tools section του system.py."""
    import os as _os
    system_path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'tools', 'system.py')
    with open(system_path, 'r', encoding='utf-8') as f:
        src = f.read()
    assert 'grep_project_files' in src, "grep_project_files not in tools/system.py"
    idx = src.find('all_tools')
    segment = src[idx:idx+2000]
    assert 'grep_project_files' in segment, "grep_project_files missing from all_tools list"
