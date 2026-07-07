# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================
import requests
import re
import html
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

def send_telegram_msg_full(text: str, prefix: str = "", max_len: int = 3500, disable_notification: bool = False):
    """Στέλνει ολόκληρο το κείμενο σε Telegram, σπάζοντάς το σε κομμάτια αν χρειαστεί
    (αντί να το κόβει στη μέση). Telegram hard limit = 4096 chars/μήνυμα."""
    full = f"{prefix}{text}" if prefix else text
    if len(full) <= max_len:
        send_telegram_msg(full, disable_notification=disable_notification)
        return
    chunks = [full[i:i + max_len] for i in range(0, len(full), max_len)]
    for idx, chunk in enumerate(chunks, 1):
        suffix = f"\n\n[{idx}/{len(chunks)}]" if len(chunks) > 1 else ""
        send_telegram_msg(chunk + suffix, disable_notification=disable_notification)


def format_for_telegram(text: str) -> str:
    """Mastro-Fix: Μετατρέπει το Markdown του LLM σε ασφαλές HTML για το Telegram."""
    if not text:
        return ""

    # Telegram HTML rejects stray angle brackets like "(<0,5g)".
    # Keep the small tag subset we intentionally support, escape everything else.
    allowed_tags = {
        "<b>": "__TG_B_OPEN__",
        "</b>": "__TG_B_CLOSE__",
        "<i>": "__TG_I_OPEN__",
        "</i>": "__TG_I_CLOSE__",
        "<u>": "__TG_U_OPEN__",
        "</u>": "__TG_U_CLOSE__",
        "<s>": "__TG_S_OPEN__",
        "</s>": "__TG_S_CLOSE__",
        "<code>": "__TG_CODE_OPEN__",
        "</code>": "__TG_CODE_CLOSE__",
        "<pre>": "__TG_PRE_OPEN__",
        "</pre>": "__TG_PRE_CLOSE__",
    }
    for tag, placeholder in allowed_tags.items():
        text = text.replace(tag, placeholder)

    text = html.escape(text, quote=False)

    for tag, placeholder in allowed_tags.items():
        text = text.replace(placeholder, tag)

    text = re.sub(r'^#{1,3}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'^[\*\-]\s+', r'• ', text, flags=re.MULTILINE)
    return text


def _plain_telegram_fallback(text: str) -> str:
    text = re.sub(r'</?(?:b|i|u|s|code|pre)>', '', text)
    return html.unescape(text)

def send_telegram_msg(text: str, disable_notification: bool = False) -> int | None:
    """Στέλνει μήνυμα στο Telegram. Επιστρέφει το message_id ή None."""
    token = TELEGRAM_TOKEN
    chat_id = TELEGRAM_CHAT_ID

    if not token or not chat_id:
        print("❌ Σφάλμα: Λείπουν τα Telegram credentials από το .env")
        return None

    safe_text = format_for_telegram(text)

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": safe_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "disable_notification": disable_notification
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            payload.pop("parse_mode")
            payload["text"] = _plain_telegram_fallback(safe_text)
            response = requests.post(url, json=payload, timeout=10)
            print(f"⚠️ Telegram API Warning: plain text (Status: {response.status_code})")
        data = response.json()
        return data.get("result", {}).get("message_id")
    except requests.exceptions.Timeout:
        print("❌ Telegram Error: Timeout.")
        return None
    except Exception as e:
        print(f"❌ Telegram Connection Error: {e}")
        return None


async def send_telegram_photo(image_path: str, caption: str = ""):
    """Στέλνει φωτογραφία στο Telegram από local path."""
    import os
    token   = TELEGRAM_TOKEN
    chat_id = TELEGRAM_CHAT_ID
    if not token or not chat_id or not os.path.exists(image_path):
        print(f"⚠️ send_telegram_photo: αρχείο δεν βρέθηκε ή credentials λείπουν ({image_path})")
        return
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        with open(image_path, "rb") as f:
            response = requests.post(
                url,
                data={"chat_id": chat_id, "caption": caption},
                files={"photo": (os.path.basename(image_path), f, "image/jpeg")},
                timeout=30
            )
        if response.status_code == 200:
            print(f"✅ [Telegram Photo]: Εικόνα στάλθηκε ({os.path.basename(image_path)})")
        else:
            print(f"⚠️ [Telegram Photo]: {response.status_code} — {response.text[:120]}")
    except Exception as e:
        print(f"❌ [Telegram Photo Error]: {e}")


def send_telegram_document(file_path: str, caption: str = "", drive_url: str = ""):
    """
    Στέλνει αρχείο στο Telegram ως document (sendDocument).
    Αν δοθεί drive_url, προσθέτει inline keyboard κουμπί "Άνοιγμα στο Google Drive".
    """
    import os, json
    token   = TELEGRAM_TOKEN
    chat_id = TELEGRAM_CHAT_ID
    if not token or not chat_id:
        print("⚠️ send_telegram_document: λείπουν credentials")
        return
    if not os.path.exists(file_path):
        send_telegram_msg(f"⚠️ Αρχείο δεν βρέθηκε: <code>{file_path}</code>")
        return

    filename = os.path.basename(file_path)
    msg_caption = caption or f"📎 <b>{filename}</b>"

    payload = {
        "chat_id":    chat_id,
        "caption":    msg_caption,
        "parse_mode": "HTML",
    }
    if drive_url:
        payload["reply_markup"] = json.dumps({
            "inline_keyboard": [[{
                "text": "📂 Άνοιγμα στο Google Drive",
                "url":  drive_url
            }]]
        })

    url = f"https://api.telegram.org/bot{token}/sendDocument"
    try:
        with open(file_path, "rb") as f:
            resp = requests.post(
                url,
                data=payload,
                files={"document": (filename, f, "application/octet-stream")},
                timeout=60
            )
        if resp.status_code == 200:
            print(f"✅ [Telegram Doc]: {filename} στάλθηκε" + (" + Drive link" if drive_url else ""))
        else:
            print(f"⚠️ [Telegram Doc]: {resp.status_code} — {resp.text[:120]}")
    except Exception as e:
        print(f"❌ [Telegram Doc Error]: {e}")
        send_telegram_msg(f"❌ Αποτυχία αποστολής αρχείου: {str(e)}")


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
