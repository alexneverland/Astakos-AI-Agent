"""Named local GPS locations available to Astakos agents."""

import json
from typing import Literal

from langchain_core.tools import tool


@tool
def manage_known_places(action: Literal["save_current", "list", "locate"],
                        name: str = "", radius_m: float = 100) -> str:
    """Save/list/locate named places alongside configured home and work.

    For an explicit owner request to remember their current place, use save_current
    with its owner-provided name. Coordinates come from fresh local GPS, never from
    guesses or an earlier assistant answer. Confirm saving only on status=saved.
    list returns configured and saved geometry. locate matches fresh GPS to their
    radii; an empty matches list is unknown, not a street/address inference.
    General profile memory is not a substitute for this registry. No external send,
    geocoder request, configuration modification or family/work flag update occurs.
    """
    from memory.known_places import list_known_places, locate_known_places, save_current_place
    try:
        if action == "save_current":
            place = save_current_place(name, radius_m)
            result = (dict(status="saved", place=place) if place is not None
                      else dict(status="unavailable", reason="no_fresh_gps"))
        elif action == "list":
            result = dict(status="listed", places=list_known_places())
        elif action == "locate":
            result = locate_known_places()
        else:
            result = dict(status="error", reason="invalid_action")
    except (OSError, ValueError, TimeoutError):
        result = dict(status="error", reason="place_storage_or_request_failed")
    return json.dumps(result, ensure_ascii=False, allow_nan=False)
