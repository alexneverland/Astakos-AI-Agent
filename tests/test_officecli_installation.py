"""Pinned executable provisioning contracts; downloads are always injected."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest


@pytest.mark.parametrize("system,machine,name", [
    ("Windows", "AMD64", "officecli-win-x64.exe"),
    ("Windows", "ARM64", "officecli-win-arm64.exe"),
    ("Linux", "x86_64", "officecli-linux-x64"),
    ("Linux", "aarch64", "officecli-linux-arm64"),
    ("Darwin", "x86_64", "officecli-mac-x64"),
    ("Darwin", "arm64", "officecli-mac-arm64"),
])
def test_selects_pinned_platform_asset(system: str, machine: str, name: str) -> None:
    """Each supported release target resolves its own architecture and artifact."""
    from services.officecli_installation import select_asset
    assert select_asset(system=system, machine=machine).name == name


def test_unsupported_platform_is_rejected() -> None:
    """Never download a convenient executable for an incompatible platform."""
    from services.officecli_installation import select_asset
    with pytest.raises(ValueError, match="Unsupported"):
        select_asset(system="Linux", machine="i686")


@pytest.mark.parametrize("payload", [b"corrupted", b"oversized content"])
def test_failed_download_preserves_existing_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: bytes) -> None:
    """Size/hash verification failure cannot replace the existing installation."""
    from services import officecli_installation as installer
    binary = installer.officecli_binary_path(tmp_path, system="Linux", allow_bundled=False)
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"old binary")
    expected = b"expected"
    monkeypatch.setattr(installer, "select_asset", lambda **kwargs: installer.OfficeAsset("fixture", len(expected), sha256(expected).hexdigest()))
    monkeypatch.setattr(installer, "urlopen", lambda *a, **k: BytesIO(payload))
    with pytest.raises(ValueError, match="verification"):
        installer.install_officecli(tmp_path, system="Linux", machine="x86_64")
    assert binary.read_bytes() == b"old binary"
    assert list(binary.parent.iterdir()) == [binary]


def test_verified_install_is_atomic_and_repeatable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fresh install uses the pinned URL; subsequent identical installs stay offline."""
    from services import officecli_installation as installer
    payload = b"verified fixture"
    asset = installer.OfficeAsset("officecli-linux-x64", len(payload), sha256(payload).hexdigest())
    monkeypatch.setattr(installer, "select_asset", lambda **kwargs: asset)
    urls = []

    def download(url: str, **kwargs: object) -> BytesIO:
        """Serve fixture bytes and retain the requested release URL."""
        urls.append(url)
        assert kwargs["timeout"] == 30
        return BytesIO(payload)

    monkeypatch.setattr(installer, "urlopen", download)
    binary = installer.install_officecli(tmp_path, system="Linux", machine="x86_64")
    assert binary.name == "officecli"
    assert binary.read_bytes() == payload
    assert urls == ["https://github.com/iOfficeAI/OfficeCLI/releases/download/v1.0.154/officecli-linux-x64"]
    installer.install_officecli(tmp_path, system="Linux", machine="x86_64")
    assert len(urls) == 1


def test_docker_fallback_is_invocation_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A mounted source can invoke the bundle, while provisioning still targets its root."""
    from services.officecli_installation import officecli_binary_path
    original = Path.is_file
    bundled = Path("/opt/astakos-tools/officecli")
    monkeypatch.setattr(Path, "is_file", lambda path: path == bundled or original(path))
    assert officecli_binary_path(tmp_path, system="Linux") == bundled
    assert officecli_binary_path(tmp_path, system="Linux", allow_bundled=False) == tmp_path / "vendor/officecli/officecli"
