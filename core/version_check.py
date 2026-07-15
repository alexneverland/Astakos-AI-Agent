"""Lightweight startup version check for Astakos.

The checker is deliberately read-only: it never modifies the installation,
credentials, databases, or user files. It only reports when a newer stable
GitHub release is available.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

REPOSITORY = "alexneverland/Astakos-AI-Agent"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
LATEST_RELEASE_PAGE = f"https://github.com/{REPOSITORY}/releases/latest"
_VERSION_RE = re.compile(r"^(?:v)?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


def _parse_version(value: str) -> Optional[Tuple[int, int, int]]:
    match = _VERSION_RE.match(value.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def get_current_version() -> str:
    version_file = Path(__file__).resolve().parents[1] / "VERSION"
    try:
        return version_file.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def get_latest_release(timeout: float = 3.0) -> Optional[dict]:
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Astakos-Version-Checker",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None

    if not isinstance(payload, dict) or not payload.get("tag_name"):
        return None
    return payload


def check_for_updates() -> None:
    """Print a non-blocking startup notice when a newer release exists."""
    if os.getenv("ASTAKOS_CHECK_UPDATES", "1").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return

    current = get_current_version()
    release = get_latest_release()
    if release is None:
        print("[Update]: Could not check GitHub releases; startup will continue.")
        return

    latest_tag = str(release.get("tag_name", "")).strip()
    current_parsed = _parse_version(current)
    latest_parsed = _parse_version(latest_tag)

    if current_parsed is None or latest_parsed is None:
        return

    if latest_parsed > current_parsed:
        release_url = str(release.get("html_url") or LATEST_RELEASE_PAGE)
        print("\n" + "=" * 64)
        print(f"[Update]: Astakos {latest_tag} is available (installed: v{current}).")
        print(f"[Update]: Release page: {release_url}")
        print("[Update]: Git install: git pull && docker compose up --build -d")
        print("[Update]: ZIP install: back up local data, then download the new release.")
        print("=" * 64 + "\n")
    else:
        print(f"[Update]: Astakos v{current} is up to date.")
