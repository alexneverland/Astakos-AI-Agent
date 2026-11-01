"""Opt-in local provisioning; never print the generated GPS credential."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import secrets
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from filelock import FileLock
from services.owntracks import write_private_json


def provision(root: Path, url: str) -> Path:
    """Create a private phone import and high-entropy credential verifier once."""
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or parsed.path != "/owntracks/"):
        raise ValueError("Use an HTTPS OwnTracks URL ending in /owntracks/, without credentials or query")
    folder = root / "credentials"
    folder.mkdir(parents=True, exist_ok=True)
    auth_file, export = folder / "owntracks-auth.json", folder / "owntracks.otrc"
    with FileLock(str(auth_file) + ".lock", timeout=5):
        if auth_file.exists():
            raise FileExistsError("OwnTracks is already provisioned; existing credentials were preserved")
        if export.exists():
            settings = json.loads(export.read_text(encoding="utf-8"))
            token = settings.get("password") if isinstance(settings, dict) else None
            if (not isinstance(settings, dict) or settings.get("_type") != "configuration"
                    or settings.get("url") != url or settings.get("username") != "owner"
                    or settings.get("deviceId") != "phone" or settings.get("mode") != 3
                    or settings.get("auth") is not True or not isinstance(token, str)
                    or len(token) != 64 or any(char not in "0123456789abcdef" for char in token)):
                raise ValueError("Partial OwnTracks configuration is invalid; existing files were preserved")
            write_private_json(auth_file, {"username": "owner", "device": "phone",
                "secret_sha256": hashlib.sha256(token.encode()).hexdigest()})
            return export
        # SHA-256 verifies this random token; this is not human password storage.
        password = secrets.token_hex(32)
        username, device = "owner", "phone"
        write_private_json(export, {
            "_type": "configuration", "mode": 3, "url": url,
            "auth": True, "username": username, "password": password,
            "deviceId": device, "tid": "OW", "monitoring": 1,
            "locatorInterval": 120, "locatorDisplacement": 0, "locatorPriority": 1,
            "ignoreInaccurateLocations": 100, "ping": 0,
            "autostartOnBoot": True, "cmd": False, "remoteConfiguration": False,
            "allowinvalidcerts": False,
        })
        write_private_json(auth_file, {"username": username, "device": device,
            "secret_sha256": hashlib.sha256(password.encode()).hexdigest()})
    return export


def main() -> int:
    """Provision explicitly and display only the private import file's path."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    try:
        export = provision(ROOT, args.url)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f"OwnTracks import created: {export}")
    print("Transfer this file privately to your phone; it contains a GPS-only credential.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
