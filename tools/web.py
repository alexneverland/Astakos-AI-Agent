# ================================================================
# Project: Astakos AI Agent 🦞
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import config
import os
import re
import json
from core.i18n import t
import urllib.parse
import unicodedata
import requests
import html
import xml.etree.ElementTree as ET
from config import NLP_CONFIG
from langchain_core.tools import tool
from typing import Annotated
from playwright.sync_api import sync_playwright
from services.messenger_intent import classify_messenger_intent
from core.messenger_draft import active_draft_status
try:
    from playwright_stealth import stealth_sync
except ImportError:
    # [MASTRO-FIX]: In some versions the function is simply called 'stealth'
    try:
        from playwright_stealth import stealth as stealth_sync
    except ImportError:
        print("⚠️ [Web Tool]: Not found: stealth_sync. Will continue without stealth mode.")
        stealth_sync = None

def remove_accents(input_str: str) -> str:
    """Removes accents and converts to lowercase."""
    if not isinstance(input_str, str):
        return ""
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    return u"".join([c for c in nfkd_form if not unicodedata.combining(c)]).lower()


def _greek_to_latin(s: str) -> str:
    """
    Basic Greek→Latin transliteration for contact matching.
    e.g., "sofia" -> "sofia"
    Used as a fallback when the query is in Latin characters.
    """
    _MAP = NLP_CONFIG.get("general", {}).get("greek_to_latin_map", {})
    return ''.join(_MAP.get(c, c) for c in s.lower())


_AMBIGUOUS_MESSENGER_TARGETS = set(NLP_CONFIG.get("web", {}).get("ambiguous_messenger_targets", []))


def _load_messenger_contacts() -> dict[str, str]:
    try:
        from memory.vector_store import get_profile_facts
        
        docs = get_profile_facts(category="contacts", limit=200)
        rows = [[d["fact"]] for d in docs]
        
        contacts = {}
        for row in rows:
            fact_str = row[0]
            if ":" in fact_str:
                k, v = fact_str.split(":", 1)
                contacts[k.strip()] = v.strip()
        
        # Load additional manual contacts from astakos_settings.json
        try:
            import json, os
            from config import SETTINGS_FILE
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    _set = json.load(f)
                    for k, v in _set.get("messenger_contacts", {}).items():
                        contacts[k.strip()] = str(v).strip()
        except Exception as e:
            print(f"⚠️ Failed to load manual messenger contacts: {e}")
                
        return {remove_accents(str(k).strip()): str(v) for k, v in contacts.items()}
    except Exception:
        return {}


def _messenger_target_status(target_entity: str) -> tuple[bool, str]:
    target = (target_entity or "").strip()
    normalized = remove_accents(target)
    if not target:
        return False, "missing target"
    if normalized in _AMBIGUOUS_MESSENGER_TARGETS:
        return False, f"ambiguous target '{target_entity}'"
    if target.startswith("http") or target.isdigit():
        return True, "direct target"

    contacts = _load_messenger_contacts()
    # 1) Exact match (accent-normalized)
    if normalized in contacts:
        return True, "known contact"
    # 2) Partial alias match
    if any(alias and (alias in normalized or normalized in alias) for alias in contacts):
        return True, "known contact"
    # 3) Greek↔Latin transliteration fallback:
    #    If the query is in Latin characters (e.g. "Sophia"), transliterate the Greek contact keys
    #    and compare. Also, "ph" → "f" phonetic equivalence (sophia → sofia).
    _is_latin_query = all(ord(c) < 0x0370 or c.isdigit() or not c.isalpha() for c in normalized)
    if _is_latin_query:
        # phonetic variants: ph→f, ck→k, c→k (before a/o/u/l/r)
        def _phonetic(s: str) -> str:
            s = s.replace("ph", "f").replace("ck", "k").replace("th", "th")
            return s
        normalized_ph = _phonetic(normalized)
        for alias in contacts:
            alias_latin = _greek_to_latin(alias)
            alias_latin_ph = _phonetic(alias_latin)
            if alias_latin == normalized or alias_latin_ph == normalized_ph:
                return True, "known contact"
            if alias_latin in normalized or normalized in alias_latin:
                return True, "known contact"
    return False, f"unknown Messenger contact '{target_entity}'"


_CHATBOT_NOISE_PATTERNS = NLP_CONFIG.get("web", {}).get("chatbot_noise_patterns", [])

def _sanitize_message_payload(text: str) -> str:
    """
    Removes chatbot meta-text from the payload before it is saved as a draft.
    Keeps only the actual message to be sent.
    """
    if not text:
        return ""
    cleaned = text.strip()
    for pattern in _CHATBOT_NOISE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    # Remove multiple blank lines
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()
    return cleaned


def _rss_text(item, tag: str) -> str:
    node = item.find(tag)
    return (node.text or "").strip() if node is not None else ""


def _clean_news_description(raw: str, max_chars: int = 220) -> str:
    if not raw:
        return ""
    text = html.unescape(raw)
    text = re.sub(r"<li>.*?</li>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    noise = t("tools.web.news_noise")
    for marker in noise:
        text = text.replace(marker, "").strip()
    if len(text) > max_chars:
        text = text[: max_chars - 3].rstrip() + "..."
    return text


def _format_rss_pub_date(pub_date: str) -> str:
    if not pub_date:
        return ""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(pub_date)
        if not dt:
            return ""
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return pub_date


def _places_tokenize(text: str) -> set[str]:
    normalized = remove_accents(text or "")
    return {tok for tok in re.findall(t("tools.web.places_regex"), normalized) if len(tok) >= 2}


_PLACES_INTENT_SYNONYMS_JSON = NLP_CONFIG.get("web", {}).get("places_intent_synonyms", {})
_PLACES_INTENT_SYNONYMS = {k: set(v) for k, v in _PLACES_INTENT_SYNONYMS_JSON.items()}


def _build_places_query_profile(query: str) -> dict:
    tokens = _places_tokenize(query)
    wanted = {
        label for label, synonyms in _PLACES_INTENT_SYNONYMS.items()
        if tokens & synonyms
    }
    return {
        "tokens": tokens,
        "wanted": wanted,
    }


def _places_text_blob(place: dict) -> str:
    parts = [
        place.get("displayName", {}).get("text", ""),
        place.get("primaryTypeDisplayName", {}).get("text", ""),
        place.get("formattedAddress", ""),
    ]
    for review in place.get("reviews", [])[:3]:
        parts.append(review.get("text", {}).get("text", ""))
    return " ".join(p for p in parts if p)


def _score_place_match(place: dict, profile: dict) -> float:
    tokens = profile.get("tokens", set())
    wanted = profile.get("wanted", set())
    blob = _places_text_blob(place)
    blob_tokens = _places_tokenize(blob)
    primary_type = remove_accents(place.get("primaryTypeDisplayName", {}).get("text", ""))
    name = remove_accents(place.get("displayName", {}).get("text", ""))
    rating = float(place.get("rating", 0) or 0)
    votes = int(place.get("userRatingCount", 0) or 0)

    score = rating * 12.0
    score += min(votes, 2500) / 120.0

    lexical_overlap = len(tokens & blob_tokens)
    score += lexical_overlap * 5.0

    if wanted:
        for label in wanted:
            synonyms = _PLACES_INTENT_SYNONYMS.get(label, set())
            synonym_hits = len(blob_tokens & synonyms)
            if synonym_hits:
                score += 10.0 + synonym_hits * 3.0
            else:
                score -= 6.0

    if "seafood" in wanted:
        if any(tok in blob_tokens for tok in set(t("tools.web.seafood_tokens"))):
            score += 8.0
        if any(tok in name for tok in ["grill", "burger", "pizza"]):
            score -= 10.0

    if "coffee" in wanted and any(tok in blob_tokens for tok in {"cafe", "coffee", "brunch", "bar"}):
        score += 8.0

    if "delivery" in wanted:
        if place.get("delivery") or place.get("takeout"):
            score += 7.0
        else:
            score -= 5.0

    if "family" in wanted and any(tok in blob_tokens for tok in set(t("tools.web.family_tokens"))):
        score += 6.0

    if "romantic" in wanted and any(tok in blob_tokens for tok in set(t("tools.web.romantic_tokens"))):
        score += 6.0

    if "restaurant" in primary_type or t("tools.web.restaurant_marker") in primary_type:
        score += 2.0

    return round(score, 3)


@tool
def relay_local_payload(target_entity: str, payload_data: str, image_path: str = "") -> str:
    """
    Saves a draft Messenger (Facebook) message.
    Use this WHEN you propose to the user to send a message,
    before obtaining their final approval.
    Optionally, provide an image_path to attach an image along with the message.
    """
    from core.messenger_draft import save_draft

    ok, reason = _messenger_target_status(target_entity)
    if not ok:
        return t("tools.web.msg_draft_err_reason", reason=reason)
    
    active, _, _ = active_draft_status()
    intent = classify_messenger_intent(payload_data or "", has_active_draft=active)

    if intent.intent in {"clarify_draft", "clear_draft"}:
        return t("tools.web.msg_draft_err_clarify")

    if not (payload_data or "").strip():
        return t("tools.web.msg_draft_err_empty")

    # Validate image path if provided
    if image_path and not os.path.exists(image_path):
        return t("tools.web.msg_draft_err_img", image_path=image_path)

    # ── Payload sanitization: removal of chatbot meta-text ─────────────
    # In plan mode, the LLM can include conversational prompts
    # or system feedback along with the actual message. We remove them.
    clean_payload = _sanitize_message_payload(payload_data)
    if not clean_payload:
        return t("tools.web.msg_draft_err_sanitized")

    save_draft(target_entity, clean_payload, image_path=image_path)

    # We return clean output — the display instructions are in prompts.md
    img_info = f"\nimage: {image_path}" if image_path else ""
    return t("tools.web.msg_draft_success", clean_payload=clean_payload, img_info=img_info)
@tool
def get_news(topic: str = "", limit: int = 10) -> str:
    """Fetches news from Google News with title, summary, source, and link."""
    try:
        topic = (topic or t("tools.web.general_topic")).strip()
        limit = max(1, min(int(limit or 10), 20))
        print(f"\033[96m[Web]: Fetching news for: {topic}...\033[0m")

        has_greek = any(t("prompts.ext_str_848") <= c <= t("prompts.ext_str_850") or t("prompts.ext_str_845") <= c <= t("prompts.ext_str_849") for c in topic)
        locale = "el&gl=GR&ceid=GR:el" if has_greek else "en&gl=US&ceid=US:en"

        url = (
            f"https://news.google.com/rss?hl={locale}"
            if topic.lower() in t("tools.web.general_topic_tokens")
            else f"https://news.google.com/rss/search?q={urllib.parse.quote(topic)}&hl={locale}"
        )

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return f"Error: Status {response.status_code}"

        items = ET.fromstring(response.text).findall(".//item")
        news = []
        for i, item in enumerate(items[:limit]):
            title = _rss_text(item, "title")
            link = _rss_text(item, "link") or _rss_text(item, "guid")
            source_el = item.find('source')
            source = (source_el.text or "").strip() if source_el is not None else ""
            source_url = source_el.attrib.get("url", "") if source_el is not None else ""
            pub_date = _rss_text(item, "pubDate")
            description = _clean_news_description(_rss_text(item, "description"))
            time_str = _format_rss_pub_date(pub_date)

            line = f"{i+1}. {title}"
            if source:
                line += f" [{source}]"
            if time_str:
                line += f" ({time_str})"
            if description:
                line += t("tools.web.news_format_desc", description=description)
            if link:
                line += t("tools.web.news_format_link", link=link)
            if source_url:
                line += t("tools.web.news_format_source", source_url=source_url)
            news.append(line)

        return "\n\n".join(news) if news else t("tools.web.no_news")
    except Exception as e:
        return f"News Error: {str(e)}"


@tool
def get_weather_forecast(location: str, days: int = 14) -> str:
    """Returns the detailed weather forecast for a region (up to 16 days)."""

    WMO_CODES = {
    0: t('weather.code_0'), 1: t('weather.code_1'), 2: t('weather.code_2'),
    3: t('weather.code_3'), 45: t('weather.code_45'), 48: t('weather.code_48'),
    51: t('weather.code_51'), 53: t('weather.code_53'), 55: t('weather.code_55'),
    61: t('weather.code_61'), 63: t('weather.code_63'), 65: t('weather.code_65'),
    71: t('weather.code_71'), 73: t('weather.code_73'), 75: t('weather.code_75'),
    80: t('weather.code_80'), 81: t('weather.code_81'), 82: t('weather.code_82'),
    95: t('weather.code_95'), 96: t('weather.code_96'), 99: t('weather.code_99'),
}

    try:
        location = (location or t("tools.web.default_location")).strip()
        days = max(1, min(int(days or 14), 16))

        geo_url = (
            "https://geocoding-api.open-meteo.com/v1/search"
            f"?name={urllib.parse.quote(location)}&count=1&language=el&format=json"
        )
        geo_resp = requests.get(geo_url, timeout=10).json()

        if "results" not in geo_resp or not geo_resp["results"]:
            return t("weather.no_location", location=location)

        lat = geo_resp["results"][0]["latitude"]
        lon = geo_resp["results"][0]["longitude"]
        place_name = geo_resp["results"][0]["name"]
        country = geo_resp["results"][0].get("country", "")
        admin = geo_resp["results"][0].get("admin1", "")

        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode"
            f"&timezone=auto&forecast_days={days}"
        )
        weather_resp = requests.get(weather_url, timeout=10).json()

        daily = weather_resp.get("daily", {})
        if not daily:
            return t("weather.no_data")

        dates = daily.get("time", [])
        t_max = daily.get("temperature_2m_max", [])
        t_min = daily.get("temperature_2m_min", [])
        precip = daily.get("precipitation_sum", [])
        wcodes = daily.get("weathercode", [])

        count = min(len(dates), len(t_max), len(t_min), len(precip), len(wcodes), days)
        if count == 0:
            return t("weather.no_full_data")

        place_bits = [place_name]
        if admin and admin != place_name:
            place_bits.append(admin)
        if country:
            place_bits.append(country)
        result = t("weather.forecast_header", place=", ".join(place_bits), count=count)
        for i in range(count):
            desc = WMO_CODES.get(wcodes[i], t("tools.web.weather_code_prefix", code=wcodes[i]))
            rain_info = f"🌧 {precip[i]:.1f}mm" if precip[i] > 0 else ""
            line = f"• {dates[i]}: {desc}  {t_min[i]}°C – {t_max[i]}°C"
            if rain_info:
                line += f"  {rain_info}"
            result += line + "\n"

        return result
    except Exception as e:
        return t("weather.error", error=str(e))


@tool
def search_goldmall_offers(query: str) -> str:
    """Deep Scan of ALL Goldmall offers without limitation."""
    search_term = t("tools.web.cinema_default") if any(x in query.lower() for x in t("tools.web.cinema_tokens")) else query

    browser = None
    try:
        print(f"\n\033[94m[DEBUG]: Full Deep Scan for: '{search_term}'\033[0m")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            page = context.new_page()

            target_url = f"https://www.goldmall.gr/search/term?search_term={search_term}"
            page.goto(target_url, timeout=30000)

            try:
                page.wait_for_selector(".deal-tile", timeout=10000)
            except:
                return t("tools.web.no_results", search_term=search_term)

            deals = page.locator(".deal-tile").all()[:5]  # max 5 for performance
            results = []

            for i, deal in enumerate(deals):
                detail_page = None
                try:
                    title_text = deal.inner_text().strip().split('\n')[0]
                    link_el = deal.locator("a").first
                    relative_link = link_el.get_attribute("href")
                    full_link = f"https://www.goldmall.gr{relative_link}"

                    print(f"\033[94m[DEBUG]: Opening Offer {i+1}/{len(deals)}: {full_link}\033[0m")

                    detail_page = context.new_page()
                    detail_page.goto(full_link, timeout=15000, wait_until="domcontentloaded")

                    raw_text = ""
                    for selector in [".offer-details", ".tab-content", ".description-container"]:
                        element = detail_page.locator(selector).first
                        if element.is_visible(timeout=2000):
                            raw_text = element.inner_text()
                            break

                    if not raw_text:
                        raw_text = detail_page.locator("body").inner_text()

                    noise_words = t("tools.web.goldmall_noise")
                    schedule_info = []
                    for line in raw_text.split('\n'):
                        clean_line = line.strip()
                        if len(clean_line) > 5 and not any(noise in clean_line for noise in noise_words):
                            if any(char.isdigit() for char in clean_line) or any(
                                day in clean_line for day in t("tools.web.goldmall_days")
                            ):
                                schedule_info.append(clean_line)

                    description = " | ".join(schedule_info[:5])
                    results.append(t("tools.web.goldmall_format", title_text=title_text, description=description if description else t("tools.web.goldmall_see_link")))

                except Exception as e:
                    print(f"\033[91m[DEBUG]: Error in offer {i}: {str(e)}\033[0m")
                    continue
                finally:
                    if detail_page:
                        try:
                            detail_page.close()
                        except:
                            pass

            return t("tools.web.goldmall_header") + "\n\n---\n\n".join(results)

    except Exception as e:
        return t("tools.web.goldmall_error", error=str(e))
    finally:
        if browser:
            try:
                browser.close()
            except:
                pass


@tool
def execute_local_pipeline(target_name: str = "", message: str = "") -> str:
    """Sends a message on Facebook Messenger by reading the saved draft.
    CALL IT ONLY after {config.USER_NAME} confirms with 'yes/send'. WITHOUT ANY ARGUMENTS."""
    import time
    import json
    import os
    from core.messenger_draft import active_draft_status, inactive_draft_message
    from config import MESSENGER_DRAFT_FILE
    from playwright.sync_api import sync_playwright

    base_dir = os.path.dirname(os.path.abspath(__file__))
    draft_file = MESSENGER_DRAFT_FILE

    # 1. [MASTRO INTERCEPTOR]: Read the draft
    image_path = ""
    if not target_name or not message:
        is_active, reason, draft = active_draft_status()
        if not is_active:
            return inactive_draft_message(reason)
        target_name = target_name or draft.get("target_name", "")
        message = message or draft.get("message", "")
        image_path = draft.get("image_path", "")
        print(f"\033[93m[Messenger]: Found draft for {target_name}. Executing...\033[0m")

    # 2. [MASTRO-ALIAS]: Convert Name to ID
    aliases = _load_messenger_contacts()
    
    aliases_lower = {k.lower(): v for k, v in aliases.items()}
    target_lower = target_name.strip().lower()

    final_id = aliases_lower.get(target_lower, None)
    if not final_id:
        for key, val in aliases_lower.items():
            if key in target_lower or target_lower in key:
                final_id = val
                print(f"[Messenger]: Partial alias match '{target_lower}' → ID '{val}'")
                break

    if not final_id:
        final_id = target_name

    # 3. [SEND]: Direct send — approval has already been granted by relay_local_payload
    profile_dir = os.path.join(base_dir, "..", "astakos_skills", "messenger_profile")

    _sent_ok = False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=False,
                args=['--disable-blink-features=AutomationControlled']
            )

            page = browser.new_page()

            if str(final_id).startswith("http"):
                chat_url = final_id
            else:
                chat_url = f"https://www.messenger.com/t/{final_id}"

            print(f"🚀 Direct navigation to chat: {chat_url}")
            page.goto(chat_url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(5.0)

            # 4a. [IMAGE ATTACHMENT]: Attach image if it exists
            if image_path and os.path.exists(image_path):
                print(f"\033[96m[Messenger]: Attaching image: {image_path}\033[0m")
                try:
                    # Messenger has a hidden file input — we find it and upload the file
                    file_input = page.locator('input[type="file"]').first
                    file_input.set_input_files(image_path)
                    # We wait for the image preview to appear (max 15s)
                    page.wait_for_selector(
                        f'img[src*="blob:"], div[aria-label*="{t("tools.web.html_noise_selector_img")}"], div[aria-label*="photo"], '
                        'div[aria-label*="image"], div[class*="image"], div[class*="photo"]',
                        timeout=15000,
                    )
                    print("\033[92m[Messenger]: Image attached ✓\033[0m")
                    time.sleep(1.0)
                except Exception as img_err:
                    print(f"\033[93m[Messenger]: ⚠️ Failed to attach image: {img_err}\033[0m")
                    print("\033[93m[Messenger]: Continuing with text-only message.\033[0m")

            # 4b. [SEND TEXT]: Typing + Enterof_thought
            # Timeout increased to 25s — Messenger SPA is sometimes slow
            chat_box = page.locator('div[role="textbox"]').last
            chat_box.wait_for(state="visible", timeout=10000)
            chat_box.click()
            if message:
                chat_box.fill(message)
                time.sleep(0.5)
            chat_box.press("Enter")
            time.sleep(3.0)
            _sent_ok = True

    except Exception as e:
        return f"❌ Error Messenger: {str(e)}"
    finally:
        try:
            browser.close()
        except:
            pass
        if _sent_ok and os.path.exists(draft_file):
            try:
                os.remove(draft_file)
            except OSError as _de:
                print(f"⚠️ [execute_local_pipeline]: draft delete failed: {_de}")

    # ── AUTO-CONFIRM pending routines ──────────────────────────────
    # If there is a TRIGGER_PENDING routine (e.g. "morning message Sophia"),_
    # we confirm this automatically after a successful send.
    try:
        from memory.routine_db import get_connection as _rdb_conn, confirm_routine, \
            mark_routine_responded, remove_pending_confirmation, clear_pending_confirmations
        _conn = _rdb_conn()
        _rows = _conn.execute(
            "SELECT id, event_name FROM routines WHERE state='trigger_pending'"
        ).fetchall()
        _conn.close()
        for _rid, _ev in _rows:
            try:
                confirm_routine(_rid)
                mark_routine_responded(_rid)
                remove_pending_confirmation(_rid)
                print(f"✅ [Messenger Auto-Confirm]: routine #{_rid} ('{_ev}') → active")
            except Exception as _ce:
                print(f"⚠️ [Messenger Auto-Confirm]: #{_rid} → {_ce}")
    except Exception as _ae:
        print(f"⚠️ [Messenger Auto-Confirm skipped]: {_ae}")

    img_suffix = t("tools.web.msg_send_img_suffix", filename=os.path.basename(image_path)) if image_path and os.path.exists(image_path) else ""
    return t("tools.web.msg_send_success", target_name=target_name, img_suffix=img_suffix)
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

@tool
def browse_url(url: str) -> str:
    """Opens a URL with a browser and returns the page text."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                accept_downloads=False
            )
            
            page = context.new_page()
            
            # [MASTRO-FIX]: Bulletproof check for stealth_sync!
            if 'stealth_sync' in globals() and stealth_sync is not None:
                try:
                    if callable(stealth_sync):
                        stealth_sync(page)  # If it is a normal function
                    elif hasattr(stealth_sync, 'stealth_sync'):
                        stealth_sync.stealth_sync(page)  # If it is a module
                except Exception as e:
                    print(f"⚠️ [Web Tool]: Stealth mode failed, continuing normally. ({e})")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(3000)
            except PlaywrightTimeoutError:
                browser.close()
                return t("tools.web.browse_timeout", url=url)

            # We remove scripts/styles/banners
            text = page.evaluate("""() => {
                const remove = document.querySelectorAll('script,style,nav,footer,header,noscript,[class*="cookie"],[class*="banner"],[id*="cookie"]');
                remove.forEach(el => el.remove());
                return document.body.innerText;
            }""")

            browser.close()

            lines = [l.strip() for l in text.splitlines() if l.strip()]
            clean_text = "\n".join(lines[:200])

            # Cloudflare / Captcha Detector
            bot_keywords = ["just a moment", "checking if the site connection is secure", "cloudflare", "attention required"]
            if any(kw in clean_text.lower() for kw in bot_keywords) or len(clean_text) < 30:
                return t("tools.web.browse_cloudflare")

            return t("tools.web.browse_success", url=url, clean_text=clean_text)

    except Exception as e:
        return t("tools.web.browse_error", error=str(e)) 
@tool
def duckduckgo_search(query: str) -> str:
    """Web search.
    FOR A SPECIFIC URL ALWAYS use browse_url."""
    from ddgs import DDGS
    from ddgs.exceptions import RatelimitException, TimeoutException, DDGSException

    # backend="auto" (the default) tries sequential/batched ALL engines (up to 8),
    # something that in fail-cascades reached 20-30+ sec. per call. Pin to 2 fast ones,
    # verified backends (verified live: duckduckgo ~1s, google ~0.5s) with 1 fallback.
    backends_to_try = ["duckduckgo", "google"]
    last_error = t("tools.web.search_err_unknown")

    for backend in backends_to_try:
        try:
            with DDGS(timeout=8) as ddgs:
                results = list(ddgs.text(query, max_results=5, backend=backend))
            if results:
                output = []
                for r in results:
                    output.append(t("tools.web.search_format_result", title=r["title"], href=r["href"], body=r["body"]))
                return "\n---\n".join(output)
            last_error = t("tools.web.search_err_empty")
        except RatelimitException:
            last_error = "rate limit"
        except TimeoutException:
            last_error = "timeout"
        except DDGSException as e:
            last_error = str(e)
        except Exception as e:
            last_error = str(e)

    return t("tools.web.search_all_failed", last_error=last_error, count=len(backends_to_try))
@tool
def search_supermarket_prices(query: str) -> str:
    """Searches for product prices from all supermarkets (e-katanalotis.gov.gr).
    Example: 'lentils', 'milk', 'olive oil'"""
    import requests
    from difflib import SequenceMatcher

    PRICES_URL = "https://warply.s3.amazonaws.com/applications/ed840ad545884deeb6c6b699176797ed/basket-retailers/prices.json?cid=1779969600000"

    try:
        r = requests.get(PRICES_URL, timeout=30)
        data = r.json()
        result = data['context']['MAPP_PRODUCTS']['result']
        merchants = {m['merchant_uuid']: m['display_name'] for m in result['merchants']}
        products = result['products']

        # Fuzzy search — removal of accents for correct matching
        query_clean = remove_accents(query).upper()
        matches = []
        for p in products:
            name = p.get('name', '')
            if query_clean in remove_accents(name).upper():
                matches.append(p)

        if not matches:
            return t("tools.web.ekat_not_found", query=query)

        # Keep the 5 most relevant
        matches = sorted(matches, key=lambda p: len(p['name']))[:5]

        output = []
        for p in matches:
            name = p['name']
            prices = p.get('prices', [])
            if not prices:
                continue
            price_lines = []
            for pr in sorted(prices, key=lambda x: x['price']):
                shop = merchants.get(pr['merchant_uuid'], f"#{pr['merchant_uuid']}")
                price_lines.append(f"  {shop}: {pr['price']:.2f}€")
            output.append(f"📦 {name}\n" + "\n".join(price_lines))

        return "\n\n".join(output) if output else t("tools.web.ekat_no_prices")

    except Exception as e:
        return f"⚠️ Error: {str(e)}"
@tool
def search_google_places(query: str = "", location: str = config.DEFAULT_CITY) -> str:
    """
    Searches for restaurants, cafes, and nightlife venues via the Google Places API (New).
    Can also be used for reverse geocoding if query is empty.
    Returns name, rating, address, type, phone, website, delivery, and reviews.
    """
    import requests
    import os
    import time
    import json
    import unicodedata
    from config import GPS_STORAGE_FILE
    profile = _build_places_query_profile(query)

    # [MASTRO-GPS-INTERCEPTOR]
    query_norm = remove_accents(query)
    if re.search(t("tools.web.ekat_near_regex"), query_norm) or location == "current":
        if os.path.exists(GPS_STORAGE_FILE):
            try:
                with open(GPS_STORAGE_FILE, "r", encoding="utf-8") as f:
                    gps = json.load(f)
                    # If the ping/location is fresh (last 24 hours)
                    if time.time() - gps['timestamp'] < 86400:
                        location = f"{gps['lat']},{gps['lon']}"
                        print(f"📍 [Web Tool]: Usage Live GPS fix: {location}")
            except Exception as e:
                print(f"⚠️ [Places GPS]: {e}")
            
    api_key = os.getenv("GOOGLE_PLACES_API_KEY", "")
    if not api_key:
        return t("tools.web.places_missing_api")

    # [MASTRO-REVERSE-GEOCODE]: Check if query is empty or generic
    # An empty query means "identify my current place", not "find a named place".
    is_reverse_geocode = not query_norm.strip()

    # [MASTRO-UPGRADE]: Added Phone, Website, Takeout, Delivery, DineIn, and Reviews to the FieldMask
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.displayName,"
            "places.rating,"
            "places.userRatingCount,"
            "places.formattedAddress,"
            "places.primaryTypeDisplayName,"
            "places.regularOpeningHours,"
            "places.googleMapsUri,"
            "places.priceLevel,"
            "places.nationalPhoneNumber,"
            "places.websiteUri,"
            "places.takeout,"
            "places.delivery,"
            "places.dineIn,"
            "places.reviews"
        )
    }

    if is_reverse_geocode and "," in location and any(c.isdigit() for c in location):
        search_url = "https://places.googleapis.com/v1/places:searchNearby"
        try:
            lat, lon = location.split(",")
            payload = {
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": float(lat), "longitude": float(lon)},
                        "radius": 50.0
                    }
                },
                "maxResultCount": 2,
                "rankPreference": "DISTANCE",
                "languageCode": "el"
            }
        except ValueError:
            search_url = "https://places.googleapis.com/v1/places:searchText"
            payload = {
                "textQuery": f"{query} {location}",
                "languageCode": "el",
                "regionCode": "GR",
                "maxResultCount": 6,
            }
    else:
        search_url = "https://places.googleapis.com/v1/places:searchText"
        # [MASTRO-FIX]: GPS coords → locationBias (the correct way, not text append)
        if "," in location and any(c.isdigit() for c in location):
            try:
                lat, lon = location.split(",")
                payload = {
                    "textQuery": query,
                    "languageCode": "el",
                    "regionCode": "GR",
                    "maxResultCount": 6,
                    "locationBias": {
                        "circle": {
                            "center": {"latitude": float(lat), "longitude": float(lon)},
                            "radius": 2000.0
                        }
                    }
                }
            except ValueError:
                payload = {"textQuery": f"{query} {location}", "languageCode": "el", "regionCode": "GR", "maxResultCount": 6}
        else:
            payload = {
                "textQuery": f"{query} {location}",
                "languageCode": "el",
                "regionCode": "GR",
                "maxResultCount": 6
            }

    try:
        resp = requests.post(search_url, headers=headers, json=payload, timeout=10)
        
        if resp.status_code != 200:
            return f"❌ Google Places Error {resp.status_code}: {resp.text[:200]}"

        data = resp.json()
        places = data.get("places", [])

        if not places:
            return t("tools.web.places_no_results", query=query, location=location)

        ranked_places = sorted(
            places,
            key=lambda place: _score_place_match(place, profile),
            reverse=True,
        )[:3]

        # ── Format results ─────────────────────────
        price_map = {
            "PRICE_LEVEL_FREE": t("tools.web.places_price_free"),
            "PRICE_LEVEL_INEXPENSIVE": "€",
            "PRICE_LEVEL_MODERATE": "€€",
            "PRICE_LEVEL_EXPENSIVE": "€€€",
            "PRICE_LEVEL_VERY_EXPENSIVE": "€€€€"
        }

        lines = [t("tools.web.places_header", query=query, location=location)]

        for i, place in enumerate(ranked_places, 1):
            name = place.get("displayName", {}).get("text", t("tools.web.places_unknown_name"))
            rating = place.get("rating", "—")
            votes = place.get("userRatingCount", 0)
            address = place.get("formattedAddress", t("tools.web.places_unknown_address"))
            ptype = place.get("primaryTypeDisplayName", {}).get("text", "")
            maps_url = place.get("googleMapsUri", "")
            price = price_map.get(place.get("priceLevel", ""), "")
            
            phone = place.get("nationalPhoneNumber", "")
            website = place.get("websiteUri", "")
            
            services = []
            if place.get("takeout"): services.append("Takeout")
            if place.get("delivery"): services.append("Delivery")
            if place.get("dineIn"): services.append("Dine-in")
            match_score = _score_place_match(place, profile)
            
            review_text = ""
            reviews = place.get("reviews", [])
            if reviews:
                first_rev = reviews[0].get("text", {}).get("text", "").replace("\n", " ").strip()
                if first_rev:
                    review_text = first_rev[:250] + "..." if len(first_rev) > 250 else first_rev

            hours_info = ""
            opening = place.get("regularOpeningHours", {})
            if opening.get("openNow") is True:
                hours_info = t("tools.web.places_open")
            elif opening.get("openNow") is False:
                hours_info = t("tools.web.places_closed")

            price_str = f" · {price}" if price else ""
            rating_str = t("tools.web.places_rating", rating=rating, votes=votes) if rating != "—" else t("tools.web.places_no_rating")
            type_str = f" · {ptype}" if ptype else ""
            
            contact_str = ""
            if phone: contact_str += f"   📞 {phone}\n"
            if website: contact_str += t("tools.web.places_website", website=website)
            
            services_str = f"   🛵 [{', '.join(services)}]\n" if services else ""
            review_str = f"   💬 \"{review_text}\"\n" if review_text else ""

            lines.append(
                f"{i}. <b>{name}</b>{price_str}\n" +
                f"   {rating_str}{type_str}{hours_info}\n" +
                f"   📌 {address}\n" +
                f"{contact_str}" +
                f"{services_str}" +
                f"{review_str}" +
                t("tools.web.places_maps", maps_url=maps_url) +
                f"   🧭 Match: {match_score}\n"
            )

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Error: {str(e)}"

@tool
def get_navigation_info(destination: str, origin: str = None, mode: str = "DRIVE") -> str:
    """Provides time, distance (with live traffic) and navigation links.
    If no origin is provided, it defaults to the configured default city.
    You can pass the result of get_current_location to the origin (e.g., '0.0,0.0').
    The mode can be "DRIVE" (driving, default) or "WALK" (walking).
    """
    import os
    import json
    import re
    import time
    import urllib.parse
    import requests
    from config import GPS_STORAGE_FILE

    home_base = config.DEFAULT_CITY
    final_origin = origin if origin else home_base

    if not origin:
        try:
            if os.path.exists(GPS_STORAGE_FILE):
                with open(GPS_STORAGE_FILE, "r", encoding="utf-8") as f:
                    gps = json.load(f)
                if time.time() - float(gps.get("timestamp", 0)) < 86400:
                    final_origin = f"{gps['lat']},{gps['lon']}"
        except Exception as e:
            print(f"⚠️ [Navigation GPS]: {e}")

    # Ensure mode is valid
    mode = mode.upper()
    if mode not in ["DRIVE", "WALK"]:
        mode = "DRIVE"

    dest_clean = urllib.parse.quote_plus(destination)
    origin_clean = urllib.parse.quote_plus(final_origin)

    dir_mode = "driving" if mode == "DRIVE" else "walking"
    search_url = f"https://www.google.com/maps/search/?api=1&query={dest_clean}"
    directions_url = f"https://www.google.com/maps/dir/?api=1&origin={origin_clean}&destination={dest_clean}&travelmode={dir_mode}"

    api_key = os.getenv("GOOGLE_PLACES_API_KEY") or os.getenv("GOOGLE_API_KEY")
    live_info = ""

    if api_key:
        try:
            def build_waypoint(waypoint_str: str):
                match = re.search(r"([-+]?\d+\.\d+)\s*,\s*([-+]?\d+\.\d+)", waypoint_str)
                if match:
                    return {
                        "location": {
                            "latLng": {
                                "latitude": float(match.group(1)),
                                "longitude": float(match.group(2))
                            }
                        }
                    }
                return {"address": waypoint_str}

            url = "https://routes.googleapis.com/directions/v2:computeRoutes"
            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": "routes.distanceMeters,routes.duration,routes.staticDuration"
            }
            body = {
                "origin": build_waypoint(final_origin),
                "destination": build_waypoint(destination),
                "travelMode": mode
            }
            
            # Routing preference TRAFFIC_AWARE is only supported for DRIVE and TWO_WHEELER
            if mode == "DRIVE":
                body["routingPreference"] = "TRAFFIC_AWARE"

            response = requests.post(url, headers=headers, json=body, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if "routes" in data and len(data["routes"]) > 0:
                    route = data["routes"][0]
                    dist_m = route.get("distanceMeters", 0)
                    dur_s = int(route.get("duration", "0s").replace("s", ""))
                    stat_s = int(route.get("staticDuration", "0s").replace("s", ""))

                    dist_km = round(dist_m / 1000.0, 1)
                    dur_min = round(dur_s / 60)
                    stat_min = round(stat_s / 60)

                    mode_icon = "🚗" if mode == "DRIVE" else "🚶‍♂️"
                    live_info = t("tools.web.dir_distance", dist_km=dist_km)
                    
                    if mode == "DRIVE":
                        live_info += t("tools.web.dir_normal_time", stat_min=stat_min)
                        live_info += t("tools.web.dir_live_time", mode_icon=mode_icon, dur_min=dur_min)
                    else:
                        live_info += t("tools.web.dir_walk_time", mode_icon=mode_icon, dur_min=dur_min)
            else:
                live_info = f"⚠️ Error Routes API ({response.status_code}): {response.text}\n\n"
        except Exception as e:
            live_info = t("tools.web.dir_live_error", error=str(e))
    else:
        live_info = t("tools.web.dir_missing_api")

    return (
        t("tools.web.dir_dest", destination=destination) +
        t("tools.web.dir_origin", final_origin=final_origin) +
        f"{live_info}" +
        t("tools.web.dir_link_map", search_url=search_url) +
        t("tools.web.dir_link_nav", directions_url=directions_url) +
        t("tools.web.dir_system_instruction")
    )

