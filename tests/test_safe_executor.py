"""
Tests για τον Safe Executor (classify_command).
Τρεξε: python -m pytest tests/ -v
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.safe_executor import classify_command, ExecPolicy


# -- BLOCKED commands ---------------------------------------------

def test_rm_rf_is_blocked():
    policy, _ = classify_command("rm -rf /")
    assert policy == ExecPolicy.BLOCKED

def test_format_disk_is_blocked():
    policy, _ = classify_command("format C:")
    assert policy == ExecPolicy.BLOCKED

def test_del_star_is_blocked():
    policy, _ = classify_command("del /f /s /q C:\\*")
    assert policy == ExecPolicy.BLOCKED


# -- REQUIRE_CONFIRMATION commands --------------------------------

def test_git_push_requires_confirmation():
    policy, _ = classify_command("git push origin main")
    assert policy == ExecPolicy.REQUIRE_CONFIRMATION

def test_git_reset_hard_requires_confirmation():
    policy, _ = classify_command("git reset --hard HEAD~1")
    assert policy == ExecPolicy.REQUIRE_CONFIRMATION

def test_register_tool_apply_via_python_requires_confirmation():
    cmd = (
        "python -c \"from astakos_skills.register_tool import register_tool; "
        "register_tool.func(tool_name='scan_receipt', dry_run=False)\""
    )
    policy, reason = classify_command(cmd)
    assert policy == ExecPolicy.REQUIRE_CONFIRMATION
    assert "register_tool" in reason

def test_register_tool_apply_via_script_requires_confirmation():
    policy, reason = classify_command("python astakos_skills/register_tool.py scan_receipt")
    assert policy == ExecPolicy.REQUIRE_CONFIRMATION
    assert "register_tool" in reason

def test_register_tool_dry_run_via_python_is_warning():
    cmd = (
        "python -c \"from astakos_skills.register_tool import register_tool; "
        "register_tool.func(tool_name='scan_receipt', dry_run=True)\""
    )
    policy, reason = classify_command(cmd)
    assert policy == ExecPolicy.WARNING
    assert "dry-run" in reason


# -- WARNING commands ---------------------------------------------

def test_pip_install_is_warning():
    policy, _ = classify_command("pip install requests")
    assert policy == ExecPolicy.WARNING

def test_npm_install_is_warning():
    policy, _ = classify_command("npm install express")
    assert policy == ExecPolicy.WARNING


# -- SAFE commands ------------------------------------------------

def test_ls_is_safe():
    policy, _ = classify_command("ls -la")
    assert policy == ExecPolicy.SAFE

def test_python_script_is_safe():
    policy, _ = classify_command("python main.py")
    assert policy == ExecPolicy.SAFE

def test_cat_file_is_safe():
    policy, _ = classify_command("cat config.py")
    assert policy == ExecPolicy.SAFE

def test_git_status_is_safe():
    policy, _ = classify_command("git status")
    assert policy == ExecPolicy.SAFE

def test_git_log_is_safe():
    policy, _ = classify_command("git log --oneline -10")
    assert policy == ExecPolicy.SAFE
