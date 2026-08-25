# ================================================================
# Project: Astakos AI Agent 🦞
# Skill:   Nutrition Analyzer — /nutrition
# Analysis of food ingredients from a photo (label/packaging).
# ================================================================

import os
from datetime import datetime
from config import BASE_DIR, RESPONSE_LANGUAGE
from core.i18n import t, load_prompt

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or ""


def analyze_nutrition(image_path: str, product_hint: str = "") -> str:
    """
    Takes a photo path, sends it to the Vision LLM, and returns
    a nutritional value / healthiness analysis in {RESPONSE_LANGUAGE}.
    """
    if not os.path.exists(image_path):
        return t("skills.nutrition_analyzer.msg_photo_not_found", path=image_path)

    hint_line = f"The product is: {product_hint}." if product_hint else ""

    prompt = load_prompt("nutrition_analyzer.md").format(
        hint_line=hint_line,
        RESPONSE_LANGUAGE=RESPONSE_LANGUAGE
    )

    try:
        from core.ai_provider import (
            CapabilityNotSupportedError,
            ProviderAuthError,
            RateLimitError,
            AIProviderError,
        )
        from core.brain import get_active_provider_adapter

        with open(image_path, "rb") as f:
            img_bytes = f.read()

        adapter = get_active_provider_adapter()
        return adapter.analyze_vision(prompt, img_bytes, mime_type="image/jpeg")
    except CapabilityNotSupportedError as exc:
        return f"Nutrition analysis is not supported by provider '{exc.provider}'."
    except ProviderAuthError as exc:
        return f"Nutrition analysis authentication failed for provider '{exc.provider}': {exc}"
    except RateLimitError as exc:
        return f"Nutrition analysis quota or rate limit exceeded for provider '{exc.provider}': {exc}"
    except AIProviderError as exc:
        return f"Nutrition analysis error ({exc.provider}): {exc}"
    except Exception as e:
        return t("skills.nutrition_analyzer.msg_analysis_error", e=e)
