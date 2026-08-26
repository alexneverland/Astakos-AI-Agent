import json
import os

from langchain_core.tools import tool


@tool
def scan_receipt(image_path: str) -> str:
    """Analyze a receipt image and return a JSON string with store, date, total, and items."""
    if not image_path or not os.path.exists(image_path):
        return json.dumps(
            {"error": f"Image file not found: {image_path}"},
            ensure_ascii=False,
        )

    from core.i18n import load_prompt
    prompt = load_prompt("scan_receipt.md")

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
        result_text = adapter.analyze_vision(prompt, img_bytes, mime_type="image/jpeg")

        from core.utils import extract_json_from_text
        parsed = extract_json_from_text(result_text)

        if isinstance(parsed, dict):
            return json.dumps(parsed, ensure_ascii=False)
        else:
            return json.dumps(
                {"error": "Model did not return valid JSON.", "raw": result_text},
                ensure_ascii=False,
            )
    except CapabilityNotSupportedError as exc:
        return json.dumps(
            {"error": f"Vision analysis is not supported by provider '{exc.provider}': {exc}"},
            ensure_ascii=False,
        )
    except ProviderAuthError as exc:
        return json.dumps(
            {"error": f"Receipt analysis authentication failed for provider '{exc.provider}': {exc}"},
            ensure_ascii=False,
        )
    except RateLimitError as exc:
        return json.dumps(
            {"error": f"Receipt analysis quota or rate limit exceeded for provider '{exc.provider}': {exc}"},
            ensure_ascii=False,
        )
    except AIProviderError as exc:
        return json.dumps(
            {"error": f"Receipt analysis error ({exc.provider}): {exc}"},
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps(
            {"error": f"Receipt analysis failed: {exc}"},
            ensure_ascii=False,
        )
