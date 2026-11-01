"""Install the pinned native Office CLI explicitly, without executing it."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.officecli_installation import VERSION, install_officecli


def main() -> int:
    """Provision the current platform's verified executable in this checkout."""
    try:
        binary = install_officecli(ROOT)
    except (OSError, ValueError) as error:
        print(f"Office CLI installation failed: {error}", file=sys.stderr)
        return 1
    print(f"Office CLI {VERSION} verified: {binary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
