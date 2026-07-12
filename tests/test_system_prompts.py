import pytest
from services.context_extractor import _CONTEXT_EXTRACTION_PROMPT
import config

def test_context_extractor_prompt_format_safety():
    """
    Ensures that the _CONTEXT_EXTRACTION_PROMPT can be formatted without throwing KeyErrors 
    due to stray curly braces (like JSON objects inside the prompt).
    """
    try:
        # Dummy values to format
        prompt = _CONTEXT_EXTRACTION_PROMPT.format(
            bot_name="TestBot",
            user_name="TestUser",
            user_text="dummy message",
            ai_text="dummy response"
        )
        assert prompt is not None
        assert "dummy message" in prompt
    except KeyError as e:
        pytest.fail(f"Prompt formatting failed with KeyError: {e}. Check for unescaped curly braces in JSON examples.")
    except Exception as e:
        pytest.fail(f"Prompt formatting failed with unexpected exception: {e}")
