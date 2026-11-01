"""Regression coverage for personal vocabulary kept out of common NLP data."""

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_json(relative_path: str) -> dict:
    """Load a project JSON fixture relative to the repository root."""
    return json.loads((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))


def test_legacy_nlp_family_aliases_are_generic() -> None:
    """Ensure common legacy NLP data does not carry installation-specific aliases."""
    legacy = _load_json("astakos_nlp.json")
    tokens = legacy["routines"]["tokens"]
    inline = legacy["routines"]["inline"]

    assert tokens["_KID1_TOKENS"] == ["μικρ", "παιδι", "kid1"]
    assert tokens["_PARTNER_TOKENS"] == ["partner"]
    assert inline["kid1_aliases"] == ["παιδι", "μικρ"]
    assert inline["partner_aliases"] == ["partner"]


def test_custom_intents_example_documents_personal_routine_aliases() -> None:
    """Ensure the personal overlay example shows each remaining routine alias location."""
    example = _load_json("astakos_custom_intents.json.example")
    routines = example["routines"]

    assert example["system_tool"]["family_markers"] == [
        "your_partner_alias",
        "your_child_alias",
    ]
    assert routines["tokens"]["_KID1_TOKENS"] == ["your_child_alias"]
    assert routines["tokens"]["_PARTNER_TOKENS"] == ["your_partner_alias"]
    assert routines["inline"]["kid1_aliases"] == ["your_child_alias"]
    assert routines["inline"]["partner_aliases"] == ["your_partner_alias"]
