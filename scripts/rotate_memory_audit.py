"""Preview or explicitly rotate old memory audit logs without opening databases."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

DEFAULT_AUDIT_DIR = Path(__file__).resolve().parents[1] / "logs" / "memory_audit"


def rotate_memory_audit_logs(
    keep_days: int = 60,
    dry_run: bool = True,
    audit_dir: str = str(DEFAULT_AUDIT_DIR),
) -> bool:
    """Remove only dated daily JSON logs older than the requested retention."""
    if keep_days < 1:
        return False
    directory = Path(audit_dir)
    try:
        if not directory.exists():
            return True
        if (not directory.is_dir() or directory.is_symlink()
                or getattr(directory.lstat(), "st_file_attributes", 0) & 0x400):
            return False
        cutoff = datetime.now().date().toordinal() - keep_days
        for path in sorted(directory.iterdir()):
            if path.suffix != ".json" or not path.is_file() or path.is_symlink():
                continue
            try:
                day = datetime.strptime(path.stem, "%Y-%m-%d").date()
            except ValueError:
                continue
            if day.isoformat() != path.stem:
                continue
            if day.toordinal() < cutoff:
                if dry_run:
                    print(f"Would remove audit log: {path.name}")
                else:
                    path.unlink(missing_ok=True)
                    print(f"Removed audit log: {path.name}")
    except OSError:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    """Default to preview; require --apply for audit-log deletion."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-days", type=int, default=60)
    parser.add_argument("--audit-dir", default=str(DEFAULT_AUDIT_DIR))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    return 0 if rotate_memory_audit_logs(args.keep_days, not args.apply, args.audit_dir) else 1


if __name__ == "__main__":
    raise SystemExit(main())
