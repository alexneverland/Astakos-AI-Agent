from collections.abc import Iterable
from pathlib import Path


def resolve_allowed_file(
    path_value: object,
    allowed_dirs: Iterable[str | Path],
) -> str | None:
    """Return an existing file only when it is inside an allowed directory."""
    if isinstance(path_value, Path):
        path_value = str(path_value)
    if not isinstance(path_value, str) or not path_value.strip():
        return None

    try:
        candidate = Path(path_value).resolve(strict=True)
    except (OSError, RuntimeError):
        return None

    if not candidate.is_file():
        return None

    for allowed_dir in allowed_dirs:
        try:
            candidate.relative_to(Path(allowed_dir).resolve(strict=True))
            return str(candidate)
        except (OSError, RuntimeError, ValueError):
            continue

    return None
