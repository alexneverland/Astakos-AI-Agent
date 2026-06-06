import json
import os

from google.genai import types
from langchain_core.tools import tool
from PIL import Image


@tool
def scan_receipt(image_path: str) -> str:
    """Analyze a receipt image and return a JSON string with store, date, total, and items."""
    if not image_path or not os.path.exists(image_path):
        return json.dumps(
            {"error": f"Image file not found: {image_path}"},
            ensure_ascii=False,
        )

    prompt = """
Analyze this shopping receipt image.
Return only valid JSON, without markdown fences or extra commentary.
Schema:
{
  "store": "store name or null",
  "date": "receipt date or null",
  "total": "numeric total amount or null",
  "currency": "currency symbol/code or null",
  "items": [
    {"name": "item name", "quantity": "quantity or null", "price": "numeric price or null"}
  ]
}
Use null when a field is not visible.
"""

    try:
        from core.brain import vertex_client

        image = Image.open(image_path)
        response = vertex_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[prompt, image],
            config=types.GenerateContentConfig(temperature=0.1),
        )

        result_text = (response.text or "").strip()
        if result_text.startswith("```json"):
            result_text = result_text[len("```json"):].strip()
        elif result_text.startswith("```"):
            result_text = result_text[len("```"):].strip()
        if result_text.endswith("```"):
            result_text = result_text[:-len("```")].strip()

        try:
            parsed = json.loads(result_text)
            return json.dumps(parsed, ensure_ascii=False)
        except json.JSONDecodeError:
            return json.dumps(
                {"error": "Model did not return valid JSON.", "raw": result_text},
                ensure_ascii=False,
            )
    except Exception as exc:
        return json.dumps(
            {"error": f"Receipt analysis failed: {exc}"},
            ensure_ascii=False,
        )
