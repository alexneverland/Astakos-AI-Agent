from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from config import BASE_DIR

LIBRARY_FILE = Path(BASE_DIR) / "astakos_skills" / "recipe_library.json"
_LIBRARY_LOCK = threading.RLock()


class RecipeLibraryError(RuntimeError):
    """Raised when the recipe library cannot be read safely."""


def _normalize(value: str) -> str:
    value = "".join(
        char
        for char in unicodedata.normalize("NFD", value.lower().strip())
        if unicodedata.category(char) != "Mn"
    )
    return " ".join(re.findall(r"[^\W_]+", value, flags=re.UNICODE))


def _load_library() -> dict[str, Any]:
    if not LIBRARY_FILE.exists():
        return {"version": 1, "recipes": []}

    try:
        data = json.loads(LIBRARY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecipeLibraryError("recipe_library_unreadable") from exc

    if not isinstance(data, dict) or not isinstance(data.get("recipes"), list):
        raise RecipeLibraryError("recipe_library_invalid_schema")
    return data


def _write_library(data: dict[str, Any]) -> None:
    LIBRARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        prefix=".recipe_library_",
        suffix=".tmp",
        dir=LIBRARY_FILE.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, LIBRARY_FILE)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def save_generated_recipe(
    name: str,
    content: str,
    *,
    external_content_sources: list[str] | None = None,
) -> dict[str, Any]:
    """Persist one explicitly named generated recipe as an immutable version."""
    name = name.strip()
    content = content.strip()
    if not name or not content:
        raise ValueError("recipe_name_and_content_required")

    with _LIBRARY_LOCK:
        library = _load_library()
        recipe = {
            "id": uuid.uuid4().hex,
            "name": name,
            "content": content,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "is_favorite": False,
            "last_cooked_at": None,
        }
        if external_content_sources:
            recipe["external_content_sources"] = sorted({
                source
                for source in external_content_sources
                if isinstance(source, str) and source
            })
        library["recipes"].append(recipe)
        _write_library(library)
        return recipe


@tool
def search_recipe_library(query: str, favorites_only: bool = False) -> str:
    """Search saved recipes and return compact ids, names, and favorite state."""
    query_tokens = set(_normalize(query).split())

    with _LIBRARY_LOCK:
        recipes = _load_library()["recipes"]

    matches = []
    for recipe in recipes:
        if favorites_only and not recipe.get("is_favorite", False):
            continue
        name = str(recipe.get("name", ""))
        name_tokens = set(_normalize(name).split())
        score = len(query_tokens & name_tokens)
        if score:
            matches.append((score, recipe))

    matches.sort(
        key=lambda item: (
            item[0],
            item[1].get("is_favorite", False),
            item[1].get("created_at", ""),
        ),
        reverse=True,
    )
    return json.dumps(
        [
            {
                "id": recipe["id"],
                "name": recipe["name"],
                "is_favorite": recipe.get("is_favorite", False),
                "last_cooked_at": recipe.get("last_cooked_at"),
            }
            for _, recipe in matches[:10]
        ],
        ensure_ascii=False,
    )


@tool
def get_saved_recipe(recipe_id: str) -> str:
    """Return the exact saved recipe content for a recipe id."""
    with _LIBRARY_LOCK:
        recipes = _load_library()["recipes"]

    for recipe in recipes:
        if recipe.get("id") == recipe_id:
            result = json.dumps(recipe, ensure_ascii=False)
            sources = recipe.get("external_content_sources", [])
            if not isinstance(sources, list):
                sources = []
            if sources:
                from core.untrusted_content import format_untrusted_tool_result

                result = format_untrusted_tool_result(
                    "persisted recipe sources: " + ", ".join(sources),
                    result,
                )
            return result
    return json.dumps({"found": False}, ensure_ascii=False)


@tool
def mark_recipe_favorite(recipe_id: str, favorite: bool = True) -> str:
    """Set favorite state for one saved recipe."""
    with _LIBRARY_LOCK:
        library = _load_library()
        for recipe in library["recipes"]:
            if recipe.get("id") == recipe_id:
                recipe["is_favorite"] = favorite
                _write_library(library)
                return json.dumps(
                    {
                        "found": True,
                        "id": recipe_id,
                        "is_favorite": favorite,
                    },
                    ensure_ascii=False,
                )
    return json.dumps({"found": False}, ensure_ascii=False)
