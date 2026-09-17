# ================================================================
# Project: Astakos AI Agent 🦞
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================
import requests
import re
import html
import os
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID


def _is_pytest_execution() -> bool:
    """Return whether this call is executing inside an active pytest test."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _suppress_test_delivery(delivery_type: str) -> bool:
    """Block every real Telegram transport while a pytest test is active."""
    if not _is_pytest_execution():
        return False
    print(f"[Test Safety]: Telegram {delivery_type} suppressed during pytest.")
    return True

def send_telegram_msg_full(text: str, prefix: str = "", max_len: int = 3500, disable_notification: bool = False) -> int | None:
    """Sends the entire text to Telegram, splitting it into chunks if necessary
    (instead of cutting it in half). Telegram hard limit = 4096 chars/message."""
    full = f"{prefix}{text}" if prefix else text
    if len(full) <= max_len:
        return send_telegram_msg(full, disable_notification=disable_notification)
    chunks = [full[i:i + max_len] for i in range(0, len(full), max_len)]
    last_id = None
    for idx, chunk in enumerate(chunks, 1):
        suffix = f"\n\n[{idx}/{len(chunks)}]" if len(chunks) > 1 else ""
        last_id = send_telegram_msg(chunk + suffix, disable_notification=disable_notification)
    return last_id


def _replace_markdown_links(text: str) -> str:
    """Convert safe Markdown links to Telegram HTML in linear time."""
    rendered: list[str] = []
    cursor = 0

    while cursor < len(text):
        link_start = text.find("[", cursor)
        if link_start < 0:
            rendered.append(text[cursor:])
            break

        rendered.append(text[cursor:link_start])
        label_end = text.find("](", link_start + 1)
        if label_end < 0:
            rendered.append(text[link_start:])
            break

        label = text[link_start + 1:label_end]
        url_start = label_end + 2
        if not label or "\n" in label or "\r" in label:
            rendered.append(text[link_start:url_start])
            cursor = url_start
            continue
        if not text.startswith(("http://", "https://"), url_start):
            rendered.append(text[link_start:url_start])
            cursor = url_start
            continue

        depth = 0
        position = url_start
        while position < len(text):
            character = text[position]
            if character.isspace() or character in '<>\"\'[]':
                rendered.append(text[link_start:position])
                cursor = position
                break
            if character == "(":
                depth += 1
            elif character == ")":
                if depth == 0:
                    url = text[url_start:position]
                    rendered.append(f'<a href="{url}">{label}</a>')
                    cursor = position + 1
                    break
                depth -= 1
            position += 1
        else:
            rendered.append(text[link_start:])
            break

    return "".join(rendered)


def format_for_telegram(text: str) -> str:
    """Mastro-Fix: Converts LLM Markdown into safe HTML for Telegram."""
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

    text = _replace_markdown_links(text)
    text = re.sub(r'^#{1,3}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'^[\*\-]\s+', r'• ', text, flags=re.MULTILINE)
    return text


def _plain_telegram_fallback(text: str) -> str:
    text = re.sub(r'</?(?:b|i|u|s|code|pre|a)(?:\s+[^>]*)?>', '', text)
    return html.unescape(text)

def send_telegram_msg(text: str, disable_notification: bool = False) -> int | None:
    """Sends a message to Telegram. Returns the message_id or None."""
    # Tests must never emit to the real bot, even if an individual test forgets
    # to mock a caller such as SafeExec or a document handler.
    if _suppress_test_delivery("message delivery"):
        return None

    token = TELEGRAM_TOKEN
    chat_id = TELEGRAM_CHAT_ID

    if not token or not chat_id:
        print("❌ Error: Telegram credentials missing from .env")
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
    """Sends a photo to Telegram from a local path."""
    if _suppress_test_delivery("photo delivery"):
        return

    token   = TELEGRAM_TOKEN
    chat_id = TELEGRAM_CHAT_ID
    if not token or not chat_id or not os.path.exists(image_path):
        print(f"⚠️ send_telegram_photo: file not found or credentials missing ({image_path})")
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
            print(f"✅ [Telegram Photo]: Image sent ({os.path.basename(image_path)})")
        else:
            print(f"⚠️ [Telegram Photo]: {response.status_code} — {response.text[:120]}")
    except Exception as e:
        print(f"❌ [Telegram Photo Error]: {e}")


def send_telegram_document(file_path: str, caption: str = "", drive_url: str = ""):
    """
    Sends a file to Telegram as a document (sendDocument).
    If drive_url is provided, it adds an inline keyboard button "Open in Google Drive".
    """
    if _suppress_test_delivery("document delivery"):
        return

    import json
    token   = TELEGRAM_TOKEN
    chat_id = TELEGRAM_CHAT_ID
    if not token or not chat_id:
        print("⚠️ send_telegram_document: credentials missing")
        return
    if not os.path.exists(file_path):
        send_telegram_msg(f"⚠️ File not found: <code>{file_path}</code>")
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
                "text": "📂 Open in Google Drive",
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
            print(f"✅ [Telegram Doc]: {filename} sent" + (" + Drive link" if drive_url else ""))
        else:
            print(f"⚠️ [Telegram Doc]: {resp.status_code} — {resp.text[:120]}")
    except Exception as e:
        print(f"❌ [Telegram Doc Error]: {e}")
        send_telegram_msg(f"❌ Failed to send file: {str(e)}")


async def send_telegram_voice(text: str):
    """Synthesize with the configured voice provider and send to Telegram."""
    if _suppress_test_delivery("voice delivery"):
        return

    from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
    from core.ai_provider import (
        CapabilityNotSupportedError,
        ProviderAuthError,
        RateLimitError,
        VoiceProviderSetupRequired,
    )
    from services.voice_output import clean_voice_reply, synthesize_voice_reply
    
    token = TELEGRAM_TOKEN
    chat_id = TELEGRAM_CHAT_ID
    
    if not token or not chat_id:
        return

    try:
        clean_text = clean_voice_reply(text)
        
        if not clean_text.strip():
            clean_text = "Boss, I sent you something technical in the chat, check it there."

        print(f"\033[95m[TTS Telegram]: Creating voice for: {clean_text[:50]}...\033[0m")

        from core.i18n import LANG
        import asyncio

        audio_bytes = await asyncio.to_thread(
            synthesize_voice_reply,
            clean_text,
            locale=LANG,
        )
        
        if not audio_bytes:
            raise RuntimeError("The configured voice provider produced no audio.")

        # Send to Telegram as voice
        url = f"https://api.telegram.org/bot{token}/sendVoice"
        response = requests.post(
            url,
            data={"chat_id": chat_id},
            files={"voice": ("voice.mp3", audio_bytes, "audio/mpeg")},
            timeout=30
        )
        
        if response.status_code == 200:
            print(f"\033[92m[TTS Telegram]: ✅ Voice sent ({len(audio_bytes)} bytes)\033[0m")
        else:
            raise RuntimeError(f"Telegram rejected voice output ({response.status_code}).")
            
    except VoiceProviderSetupRequired as e:
        from core.i18n import t

        print(f"❌ Voice Output Setup Error: {e}")
        send_telegram_msg(t("clients.telegram_bot.voice_output_setup_required"))
        send_telegram_msg(text)
    except ProviderAuthError as e:
        from core.i18n import t

        print(f"❌ Voice Output Auth Error: {e}")
        send_telegram_msg(t("clients.telegram_bot.voice_output_auth_failed"))
        send_telegram_msg(text)
    except RateLimitError as e:
        from core.i18n import t

        print(f"❌ Voice Output Rate Limit: {e}")
        send_telegram_msg(t("clients.telegram_bot.voice_output_rate_limited"))
        send_telegram_msg(text)
    except CapabilityNotSupportedError as e:
        from core.i18n import t

        print(f"❌ Voice Output Capability Error: {e}")
        send_telegram_msg(t("clients.telegram_bot.voice_output_unsupported"))
        send_telegram_msg(text)
    except Exception as e:
        print(f"❌ Voice Output Error: {e}")
        send_telegram_msg(text)
