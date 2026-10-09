"""Release entrypoint contracts in a prebuilt, network-isolated Linux container.

Set ASTAKOS_TEST_RELEASE_IMAGE to a local image built from Dockerfile.release.
No real volumes, credentials, provider requests or messaging transports are used.
"""
import base64
import json
import os
from pathlib import Path
import subprocess

import pytest


@pytest.fixture
def image() -> str:
    """Require an explicitly selected local image, never pull one during tests."""
    selected = os.environ.get("ASTAKOS_TEST_RELEASE_IMAGE")
    if not selected:
        pytest.skip("Set ASTAKOS_TEST_RELEASE_IMAGE for isolated release verification")
    subprocess.run(["docker", "image", "inspect", selected], check=True, capture_output=True)
    return selected


def _entrypoint() -> str:
    """Read the current script or a selected historical revision for RED evidence."""
    revision = os.environ.get("ASTAKOS_TEST_ENTRYPOINT_REVISION")
    if revision:
        return subprocess.check_output(["git", "show", f"{revision}:docker/release-entrypoint.sh"], text=True)
    return (Path(__file__).resolve().parents[1] / "docker/release-entrypoint.sh").read_text(encoding="utf-8")


def _run(image: str, script: str) -> str:
    """Execute synthetic fixtures inside a disposable container with no network."""
    result = subprocess.run(["docker", "run", "--rm", "--pull=never", "--network=none",
        "--entrypoint", "python", image, "-c", script], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize("existing", [False, True])
def test_release_refresh_seeds_fresh_state_and_preserves_existing(image: str, existing: bool) -> None:
    """Run the real rsync entrypoint against a fresh and an established fixture."""
    encoded = base64.b64encode(_entrypoint().encode()).decode()
    script = f'''
import base64, json, pathlib, subprocess, tempfile
root = pathlib.Path(tempfile.mkdtemp())
source, target = root / "source", root / "target"
source.mkdir(); target.mkdir()
def put(base, name, value):
    path = base / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(value)
put(source, "boot.py", "print('fixture-boot-ok')")
put(source, "astakos_context_schema.json", "default-schema")
put(source, "core/capability_registry.json", "new-registry")
put(source, "locales/en.json", "new-locale")
put(source, "vendor/officecli/officecli", "native-tool")
put(source, ".env.example", "public-template")
protected = {{
    "astakos_context_schema.json": "owner-schema",
    "astakos_working_memory.json": "owner-memory",
    "astakos_routine_context_questions.json": "owner-question",
    "behavioral_conversation_preferences.json": "owner-preference",
    "scheduler_state.json": "owner-scheduler",
    "astakos_skills/food_history.json": "owner-meals",
    "astakos_skills/recipe_library.json": "owner-recipes",
    "matrix_store/crypto.db": "owner-crypto",
    "matrix_media/file.bin": "owner-media",
    "backups/recovery.age": "owner-backup",
    ".daily-backup-status.json": "owner-backup-status",
    "run_matrix.lock": "owner-lock",
    "astakos_state.db": "owner-database",
    ".env": "owner-environment",
    ".env.private": "owner-private-environment",
}}
if {existing!r}:
    for name, value in protected.items(): put(target, name, value)
    put(target, "core/capability_registry.json", "old-registry")
    put(target, "locales/en.json", "old-locale")
    put(target, "obsolete_code.py", "obsolete")
    # Old release files predate the immutable source; avoid rsync's same-size,
    # same-second quick-check treating synthetic old/new strings as identical.
    import os
    for name in ["core/capability_registry.json", "locales/en.json"]:
        os.utime(target / name, (1, 1))
entry = base64.b64decode("{encoded}").decode().replace("/opt/astakos", str(source)).replace("/app", str(target))
shell = root / "entry.sh"; shell.write_text(entry)
result = subprocess.run(["/bin/sh", str(shell)], capture_output=True, text=True)
assert result.returncode == 0, result.stderr
assert "fixture-boot-ok" in result.stdout
if {existing!r}:
    for name, value in protected.items():
        assert (target / name).is_file(), "removed " + name
        assert (target / name).read_text() == value, "overwritten " + name
    assert not (target / "obsolete_code.py").exists()
else:
    assert (target / "astakos_context_schema.json").read_text() == "default-schema"
    assert not (target / "astakos_working_memory.json").exists()
assert (target / "core/capability_registry.json").read_text() == "new-registry"
assert (target / "locales/en.json").read_text() == "new-locale"
assert (target / "vendor/officecli/officecli").read_text() == "native-tool"
assert (target / ".env.example").read_text() == "public-template"
print("release-fixture-ok")
'''
    assert "release-fixture-ok" in _run(image, script)


def test_release_image_has_native_office_and_clean_state(image: str) -> None:
    """Check the actual built image inventory and Linux executable, not mocks."""
    output = _run(image, '''
from pathlib import Path
import subprocess
root = Path('/opt/astakos')
for name in ['.env', 'astakos_working_memory.json', 'astakos_sessions.json',
             'astakos_settings.json', 'behavioral_initiative_state.json',
             'astakos_routines.db', 'matrix_store', 'backups']:
    assert not (root / name).exists(), 'private runtime packaged: ' + name
assert (root / 'core/capability_registry.json').is_file()
assert (root / 'locales/en.json').is_file()
assert not (root / 'vendor/officecli/officecli.exe').exists()
result = subprocess.run([str(root / 'vendor/officecli/officecli'), '--version'], capture_output=True, text=True, check=True)
assert '1.0.154' in result.stdout
from services.officecli_installation import officecli_binary_path
assert officecli_binary_path('/tmp/empty-source-mount').is_file()
assert str(officecli_binary_path('/tmp/empty-source-mount')) == '/opt/astakos-tools/officecli'
print('clean-image-ok')
''')
    assert "clean-image-ok" in output


def test_native_linux_office_files(image: str) -> None:
    """Create and edit real Office fixtures and validate their stored OpenXML."""
    output = _run(image, '''
import os, subprocess, tempfile, zipfile
from pathlib import Path
os.environ.update(OFFICECLI_SKIP_UPDATE='1', OFFICECLI_NO_AUTO_RESIDENT='1')
binary = '/opt/astakos/vendor/officecli/officecli'
root = Path(tempfile.mkdtemp())
def run(*args):
    return subprocess.run([binary, *map(str, args)], capture_output=True, text=True, check=True).stdout
for extension in ['docx', 'xlsx', 'pptx']:
    path = root / ('fixture.' + extension)
    run('create', path)
    if extension == 'docx': run('add', path, '/body', '--type', 'paragraph', '--prop', 'text=Καλημέρα')
    elif extension == 'xlsx': run('set', path, '/Sheet1/A1', '--prop', 'value=42')
    else: run('add', path, '/', '--type', 'slide', '--prop', 'title=Καλημέρα')
    report = run('validate', path)
    assert 'no errors found' in report.lower(), report
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        content = ''.join(archive.read(name).decode('utf-8') for name in archive.namelist() if name.endswith('.xml'))
        assert ('42' if extension == 'xlsx' else 'Καλημέρα') in content
print('native-office-fixtures-ok')
''')
    assert "native-office-fixtures-ok" in output
