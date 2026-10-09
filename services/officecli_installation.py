"""Explicit pinned Office CLI provisioning; imports never download or execute."""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import platform
import tempfile
from urllib.request import urlopen


VERSION = "1.0.154"


@dataclass(frozen=True)
class OfficeAsset:
    """Official release identity, byte length and SHA-256 verification boundary."""
    name: str
    size: int
    sha256: str


# Official GitHub release asset digests, checked against v1.0.154 on 2026-10-09.
ASSETS = {
    ("Windows", "x64"): OfficeAsset("officecli-win-x64.exe", 33497000, "50a57626ff7c5b11034c23368312cdafbd436cf81eb149c81dc488e027a56e7e"),
    ("Windows", "arm64"): OfficeAsset("officecli-win-arm64.exe", 33939380, "9460ee2064301ea5520d9879d93c780b47cd07faf679f73ac5d449e067651a7c"),
    ("Linux", "x64"): OfficeAsset("officecli-linux-x64", 35428709, "ac57d4d94209c21e34fc133eea2b55670e5f966a9e8e6b68f656b9410db5dbae"),
    ("Linux", "arm64"): OfficeAsset("officecli-linux-arm64", 34840071, "7e8d23026e678fb5222e55e88a5e4b80226738cb83592ae2268b8a17e480a765"),
    ("Darwin", "x64"): OfficeAsset("officecli-mac-x64", 34817632, "d7a63396a76f436c6bc993092c999ee1d37f985eacce2b09a3a3eba37c9baa4f"),
    ("Darwin", "arm64"): OfficeAsset("officecli-mac-arm64", 33867504, "a05c82e04bd0f283ea309f20e4092d540632438cba8ecbf192e65209f780c372"),
}


def select_asset(*, system: str | None = None, machine: str | None = None) -> OfficeAsset:
    """Select a supported native artifact, rejecting unknown architectures."""
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    try:
        return ASSETS[(system, arch)]
    except KeyError:
        raise ValueError(f"Unsupported Office CLI platform: {system}/{machine}") from None


def officecli_binary_path(root: str | Path, *, system: str | None = None,
                         allow_bundled: bool = True) -> Path:
    """Resolve a native tool, retaining Docker's copy across source bind mounts."""
    selected_system = system or platform.system()
    name = "officecli.exe" if selected_system == "Windows" else "officecli"
    local = Path(root) / "vendor" / "officecli" / name
    bundled = Path("/opt/astakos-tools/officecli")
    if allow_bundled and selected_system == "Linux" and not local.is_file() and bundled.is_file():
        return bundled
    return local


def _verified(path: Path, asset: OfficeAsset) -> bool:
    """Check exact size and content without loading executable bytes into memory."""
    if not path.is_file() or path.stat().st_size != asset.size:
        return False
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest() == asset.sha256


def install_officecli(root: str | Path, *, system: str | None = None,
                      machine: str | None = None) -> Path:
    """Download, verify and atomically provision the pinned native executable.

    The existing binary survives download/hash failures. This function never
    executes upstream installers, configures MCP or changes application state.
    """
    asset = select_asset(system=system, machine=machine)
    binary = officecli_binary_path(root, system=system, allow_bundled=False)
    if _verified(binary, asset):
        if (system or platform.system()) != "Windows":
            binary.chmod(0o755)
        return binary
    binary.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/iOfficeAI/OfficeCLI/releases/download/v{VERSION}/{asset.name}"
    with tempfile.TemporaryDirectory(prefix=".officecli-install-", dir=binary.parent) as directory:
        staged = Path(directory) / binary.name
        size = 0
        with urlopen(url, timeout=30) as response, staged.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > asset.size:
                    raise ValueError("Office CLI download verification failed: size")
                output.write(chunk)
        if not _verified(staged, asset):
            raise ValueError("Office CLI download verification failed: SHA-256/size")
        if (system or platform.system()) != "Windows":
            staged.chmod(0o755)
        os.replace(staged, binary)
    return binary
