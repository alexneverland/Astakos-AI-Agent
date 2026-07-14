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

    from core.i18n import load_prompt
    prompt = load_prompt("scan_receipt.md")

    try:
        from core.brain import llm
        import base64
        from langchain_core.messages import HumanMessage
        
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")
        
        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
                },
            ]
        )
        response = llm.invoke([message])
        from core.utils import clean_message
        result_text = clean_message(response.content)
        from core.utils import extract_json_from_text
        parsed = extract_json_from_text(result_text)
        
        if isinstance(parsed, dict):
            return json.dumps(parsed, ensure_ascii=False)
        else:
            return json.dumps(
                {"error": "Model did not return valid JSON.", "raw": result_text},
                ensure_ascii=False,
            )
    except Exception as exc:
        return json.dumps(
            {"error": f"Receipt analysis failed: {exc}"},
            ensure_ascii=False,
        )
