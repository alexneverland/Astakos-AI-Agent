"""Parse internal generated-file markers from assistant replies."""

from __future__ import annotations

import re
from dataclasses import dataclass

_CREATED_FILE_PATTERN = re.compile(
    r"\[(?P<marker>CREATED_FILE|SEND_PHOTO):\s*(?P<path>.*?)\]",
    re.DOTALL,
)
_MAX_CREATED_FILES = 5


@dataclass(frozen=True)
class CreatedOutput:
    """One internal output marker with its transport presentation kind."""

    path: str
    kind: str


@dataclass(frozen=True)
class CreatedFileResult:
    """Visible assistant text and bounded local paths requested for delivery."""

    text: str
    outputs: tuple[CreatedOutput, ...] = ()

    @property
    def paths(self) -> tuple[str, ...]:
        """Return attachment paths in marker order for generic transports."""
        return tuple(output.path for output in self.outputs)


def extract_created_files(reply: str) -> CreatedFileResult:
    """Remove all internal markers and retain at most five non-empty paths."""
    raw = str(reply or "")
    outputs: list[CreatedOutput] = []
    for match in _CREATED_FILE_PATTERN.finditer(raw):
        path = match.group("path").strip()
        if path and len(outputs) < _MAX_CREATED_FILES:
            kind = "photo" if match.group("marker") == "SEND_PHOTO" else "file"
            outputs.append(CreatedOutput(path=path, kind=kind))
    visible = _CREATED_FILE_PATTERN.sub("", raw).strip()
    return CreatedFileResult(text=visible, outputs=tuple(outputs))
