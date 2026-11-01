"""Shared story-generation application boundary."""

from __future__ import annotations

from typing import Any


def generate_story(theme: str, characters: str) -> dict[str, Any]:
    """Generate one story and its optional local images."""
    from astakos_skills.story_maker import make_story

    return dict(make_story(theme, characters))
