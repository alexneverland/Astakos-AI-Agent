# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================
import requests
import re
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

def format_for_telegram(text: str) -> str:
    """Mastro-Fix: Μετατρέπει το Markdown του LLM σε ασφαλές HTML για το Telegram."""
    if not text:
        return ""
    # 1. Μετατροπή Headers (### Τίτλος -> <b>Τίτλος</b>)
    text = re.sub(r'^#{1,3}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
    # 2. Μετατροπή Bold (**κείμενο** -> <b>κείμενο</b>)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # 3. Διόρθωση στις λίστες (για να μη χτυπάει το HTML)
    text = re.sub(r'^[\*\-]\s+', r'• ', text, flags=re.MULTILINE)
    return text

def send_telegram_msg(text: str):
    """Στέλνει μήνυμα στο Telegram."""
    token = TELEGRAM_TOKEN
    chat_id = TELEGRAM_CHAT_ID

    if not token or not chat_id:
        print("❌ Σφάλμα: Λείπουν τα Telegram credentials από το .env")
        return

    # Περνάμε το κείμενο από το "πλυντήριο"
    safe_text = format_for_telegram(text)

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": safe_text,
        "parse_mode": "HTML",  # <--- Γυρίσαμε σε HTML που είναι πιο ανθεκτικό
        "disable_web_page_preview": True
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            # Το Fallback σου (αν κάτι πάει στραβά, στέλνει απλό κείμενο)
            payload.pop("parse_mode")
            requests.post(url, json=payload, timeout=10)
            print(f"⚠️ Telegram API Warning: plain text (Status: {response.status_code})")
    except requests.exceptions.Timeout:
        print("❌ Telegram Error: Timeout.")
    except Exception as e:
        print(f"❌ Telegram Connection Error: {e}")
def send_telegram_voice(text: str):
    """Μετατρέπει το κείμενο σε ήχο και το στέλνει ως φωνητικό μήνυμα."""
    import os
    from gtts import gTTS
    
    token = TELEGRAM_TOKEN
    chat_id = TELEGRAM_CHAT_ID
    
    if not token or not chat_id:
        return

    try:
        # Δημιουργία MP3
        tts = gTTS(text=text, lang='el')
        audio_path = "astakos_reply.mp3"
        tts.save(audio_path)
        
        # Αποστολή στο Telegram
        url = f"https://api.telegram.org/bot{token}/sendVoice"
        with open(audio_path, 'rb') as audio_file:
            response = requests.post(
                url, 
                data={"chat_id": chat_id}, 
                files={"voice": audio_file},
                timeout=20
            )
        
        # Καθάρισμα του αρχείου
        if os.path.exists(audio_path):
            os.remove(audio_path)
            
    except Exception as e:
        print(f"❌ Telegram Voice Error: {e}")        