"""Shared application services for explicit photo-analysis commands."""

from __future__ import annotations


def analyze_nutrition_photo(image_path: str) -> str:
    """Analyze one local nutrition-label photo with the configured provider."""
    from astakos_skills.nutrition_analyzer import analyze_nutrition

    return str(analyze_nutrition(image_path))


def scan_receipt_photo(image_path: str) -> str:
    """Scan one local receipt photo with the configured provider."""
    from astakos_skills.scan_receipt import scan_receipt

    return str(scan_receipt.invoke({"image_path": image_path}))
