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
    text = re.sub(r'^#{1,3}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'^[\*\-]\s+', r'• ', text, flags=re.MULTILINE)
    return text

def send_telegram_msg(text: str):
    """Στέλνει μήνυμα στο Telegram."""
    token = TELEGRAM_TOKEN
    chat_id = TELEGRAM_CHAT_ID

    if not token or not chat_id:
        print("❌ Σφάλμα: Λείπουν τα Telegram credentials από το .env")
        return

    safe_text = format_for_telegram(text)

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": safe_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            payload.pop("parse_mode")
            requests.post(url, json=payload, timeout=10)
            print(f"⚠️ Telegram API Warning: plain text (Status: {response.status_code})")
    except requests.exceptions.Timeout:
        print("❌ Telegram Error: Timeout.")
    except Exception as e:
        print(f"❌ Telegram Connection Error: {e}")


async def send_telegram_voice(text: str):
    """
    [MASTRO-FIX]: Χρησιμοποιεί edge-tts αντί για gTTS.
    Ίδια φωνή με το Web UI (el-GR-NestorasNeural), πολύ καλύτερη ποιότητα.
    """
    import os
    import re
    import edge_tts
    import io
    from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
    
    token = TELEGRAM_TOKEN
    chat_id = TELEGRAM_CHAT_ID
    
    if not token or not chat_id:
        return

    try:
        # Καθαρισμός κειμένου
        clean_text = text
        clean_text = re.sub(r'```.*?```', '', clean_text, flags=re.DOTALL)
        clean_text = re.sub(r'\[.*?\]', '', clean_text)
        clean_text = re.sub(r'[*_#`~]', '', clean_text)
        clean_text = " ".join(clean_text.split())
        
        if not clean_text.strip():
            clean_text = "Μάστορα, σου έστειλα κάτι τεχνικό στο τσατ, δες το εκεί."

        print(f"\033[95m[TTS Telegram]: Δημιουργία φωνής για: {clean_text[:50]}...\033[0m")

        # edge-tts — ίδια φωνή με το Web UI
        voice = "el-GR-NestorasNeural"
        communicate = edge_tts.Communicate(clean_text, voice, rate="+15%", volume="+10%")
        
        audio_buffer = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_buffer.write(chunk["data"])
        
        audio_buffer.seek(0)
        audio_bytes = audio_buffer.read()
        
        if not audio_bytes:
            print("❌ edge-tts: Δεν παράχθηκε ήχος.")
            return

        # Αποστολή στο Telegram ως voice
        url = f"https://api.telegram.org/bot{token}/sendVoice"
        response = requests.post(
            url,
            data={"chat_id": chat_id},
            files={"voice": ("voice.mp3", audio_bytes, "audio/mpeg")},
            timeout=30
        )
        
        if response.status_code == 200:
            print(f"\033[92m[TTS Telegram]: ✅ Φωνητικό στάλθηκε ({len(audio_bytes)} bytes)\033[0m")
        else:
            print(f"⚠️ Telegram Voice Error: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"❌ Voice Output Error: {e}")