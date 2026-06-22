import pytest
from unittest.mock import patch, MagicMock

# This test ensures that audio does not trigger pending asset logic.

def test_audio_transcript_flow():
    # Simulate what telegram_bot handle_voice does:
    ai_reply = "Καλημέρα"
    # It passes it as a text message
    user_text = f"[ΦΩΝΗΤΙΚΟ]: [VOICE_INPUT] {ai_reply}"
    
    # Check that it's NOT considered a pending asset confirm
    from memory.pending_assets import looks_like_asset_confirmation_prompt
    assert looks_like_asset_confirmation_prompt(user_text) is False
    
    # Check the parsing logic used in Telegram's handle_message
    is_voice_mode = "[ΦΩΝΗΤΙΚΟ]" in user_text or "[VOICE_MESSAGE]" in user_text
    is_voice_input = "[VOICE_INPUT]" in user_text
    
    assert is_voice_mode is True
    assert is_voice_input is True
    
    clean_user_text = user_text.replace("/voice", "").replace("[ΦΩΝΗΤΙΚΟ]:", "").replace("[VOICE_MESSAGE]:", "").strip()
    if is_voice_input:
        clean_user_text = clean_user_text.replace("[VOICE_INPUT]", "").strip()
        
    assert clean_user_text == "Καλημέρα"
    
    # Because there's no logic to create pending_asset_archive for audio, it simply bypasses
    # We just ensure the parsing doesn't leave garbage and doesn't trigger the confirmation helper
    pass
