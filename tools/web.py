# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import os
import re
import json
import urllib.parse
import unicodedata
import requests
import html
import xml.etree.ElementTree as ET
from langchain_core.tools import tool
from typing import Annotated
from playwright.sync_api import sync_playwright
from services.messenger_intent import classify_messenger_intent
from core.messenger_draft import active_draft_status
try:
    from playwright_stealth import stealth_sync
except ImportError:
    # [MASTRO-FIX]: Σε κάποιες εκδόσεις η συνάρτηση λέγεται σκέτο 'stealth'
    try:
        from playwright_stealth import stealth as stealth_sync
    except ImportError:
        print("⚠️ [Web Tool]: Δεν βρέθηκε το stealth_sync. Θα συνεχίσω χωρίς stealth mode.")
        stealth_sync = None

def remove_accents(input_str: str) -> str:
    """Αφαιρεί τόνους και μετατρέπει σε πεζά."""
    if not isinstance(input_str, str):
        return ""
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    return u"".join([c for c in nfkd_form if not unicodedata.combining(c)]).lower()


def _greek_to_latin(s: str) -> str:
    """
    Βασική Greek→Latin transliteration για contact matching.
    π.χ. "σοφια" → "sofia", "αλεξανδρος" → "alexandros"
    Χρησιμοποιείται ως fallback όταν το query είναι λατινικό.
    """
    _MAP = {
        'α':'a','β':'v','γ':'g','δ':'d','ε':'e','ζ':'z','η':'i',
        'θ':'th','ι':'i','κ':'k','λ':'l','μ':'m','ν':'n','ξ':'x',
        'ο':'o','π':'p','ρ':'r','σ':'s','ς':'s','τ':'t','υ':'i',
        'φ':'f','χ':'h','ψ':'ps','ω':'o',
    }
    return ''.join(_MAP.get(c, c) for c in s.lower())


_AMBIGUOUS_MESSENGER_TARGETS = {
    "friend", "friends", "φιλε", "φιλος", "φιλους", "μαστορα", "mastora",
    "user", "χρηστη", "αυτον", "αυτην", "καποιον", "καποια", "unknown",
}


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
    #    Αν το query είναι λατινικό (π.χ. "Sophia"), transliterate τα Greek contact keys
    #    και σύγκρινε. Επίσης, "ph" → "f" phonetic equivalence (sophia → sofia).
    _is_latin_query = all(ord(c) < 0x0370 or c.isdigit() or not c.isalpha() for c in normalized)
    if _is_latin_query:
        # phonetic variants: ph→f, ck→k, c→k (πριν από a/o/u/l/r)
        def _phonetic(s: str) -> str:
            s = s.replace("ph", "f").replace("ck", "k").replace("th", "θ")
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


_CHATBOT_NOISE_PATTERNS = [
    # Chatbot meta-text που δεν πρέπει να σταλεί
    r"θέλεις αλλαγές[^.]*\?",
    r"θελεις αλλαγεσ[^.]*\?",
    r"να το στείλω[^.]*\?",
    r"να το στειλω[^.]*\?",
    r"το αποθήκευσα[^.]*\.",
    r"το αποθηκευσα[^.]*\.",
    r"αποθήκευσα[^.]*\.",
    r"αποθηκευσα[^.]*\.",
    r"ετοιμάζω[^.]*\.",
    r"ετοιμαζω[^.]*\.",
    r"μήνυμα(?:\s+προς\s+\S+)?\s*:\s*",  # "Μήνυμα προς Σοφία:"
    r"(?:στέλνω|στελνω|στέλνουμε|στελνουμε)\s+(?:το\s+)?μήνυμα[^.]*\.",
]

def _sanitize_message_payload(text: str) -> str:
    """
    Αφαιρεί chatbot meta-text από το payload πριν αποθηκευτεί ως draft.
    Κρατά μόνο το πραγματικό μήνυμα προς αποστολή.
    """
    if not text:
        return ""
    cleaned = text.strip()
    for pattern in _CHATBOT_NOISE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    # Αφαίρεση πολλαπλών κενών γραμμών
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
    noise = [
        "Full coverage",
        "Πλήρης κάλυψη",
        "View Full Coverage",
    ]
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
    return {tok for tok in re.findall(r"[a-zA-Zα-ωΑ-Ω0-9]+", normalized) if len(tok) >= 2}


_PLACES_INTENT_SYNONYMS = {
    "seafood": {
        "ψαροταβερνα", "ψαροταβερνες", "ψαρι", "ψαρια", "θαλασσινα", "seafood", "fish", "taverna",
    },
    "meat": {
        "μπριζολαδικο", "μπριζολα", "κρεας", "σουβλακια", "ψησταρια", "grill", "steak", "burger",
    },
    "coffee": {
        "καφε", "καφεδες", "cafe", "coffee", "brunch", "espresso", "barista",
    },
    "dessert": {
        "γλυκο", "παγωτο", "waffle", "crepe", "dessert", "ζαχαροπλαστειο",
    },
    "family": {
        "παιδια", "παιδι", "οικογενεια", "family", "kid", "kids",
    },
    "romantic": {
        "ρομαντικο", "ησυχο", "quiet", "romantic", "sunset", "view",
    },
    "delivery": {
        "delivery", "takeout", "πακετο", "ντελιβερι", "take away",
    },
}


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
        if any(tok in blob_tokens for tok in {"ψαρι", "ψαρια", "θαλασσινα", "fish", "seafood"}):
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

    if "family" in wanted and any(tok in blob_tokens for tok in {"family", "kids", "παιδια", "παιδι"}):
        score += 6.0

    if "romantic" in wanted and any(tok in blob_tokens for tok in {"view", "sunset", "ρομαντικο", "ησυχο"}):
        score += 6.0

    if "restaurant" in primary_type or "εστιατορ" in primary_type:
        score += 2.0

    return round(score, 3)


@tool
def relay_local_payload(target_entity: str, payload_data: str, image_path: str = "") -> str:
    """
    Αποθηκεύει ένα προσχέδιο μηνύματος Messenger (Facebook).
    Χρησιμοποίησέ το ΟΤΑΝ προτείνεις στον χρήστη να στείλει ένα μήνυμα,
    πριν πάρεις την τελική του έγκριση.
    Προαιρετικά, δώσε image_path για να επισυναφθεί εικόνα μαζί με το μήνυμα.
    """
    from core.messenger_draft import save_draft

    ok, reason = _messenger_target_status(target_entity)
    if not ok:
        return (
            "❌ Δεν αποθήκευσα Messenger draft.\n"
            f"Λόγος: {reason}.\n"
            "Δώσε ρητό παραλήπτη από τις επαφές, π.χ. `Σοφία`, ή Messenger URL/ID."
        )
    
    active, _, _ = active_draft_status()
    intent = classify_messenger_intent(payload_data or "", has_active_draft=active)

    if intent.intent in {"clarify_draft", "clear_draft"}:
        return "❌ Δεν αποθήκευσα Messenger draft. Αυτό το μήνυμα μοιάζει με διευκρίνιση ή κλείσιμο draft, όχι με νέο draft."

    if not (payload_data or "").strip():
        return "❌ Δεν αποθήκευσα Messenger draft. Δεν δόθηκε νέο κείμενο μηνύματος."

    # Validate image path if provided
    if image_path and not os.path.exists(image_path):
        return f"❌ Δεν αποθήκευσα Messenger draft. Η εικόνα δεν βρέθηκε: {image_path}"

    # ── Payload sanitization: αφαίρεση chatbot meta-text ─────────────
    # Στο plan mode το LLM μπορεί να συμπεριλάβει conversational prompts
    # ή system feedback μαζί με το πραγματικό μήνυμα. Τα αφαιρούμε.
    clean_payload = _sanitize_message_payload(payload_data)
    if not clean_payload:
        return "❌ Δεν αποθήκευσα Messenger draft. Το μήνυμα ήταν κενό μετά το sanitization."

    save_draft(target_entity, clean_payload, image_path=image_path)

    # Επιστρέφουμε clean output — οι οδηγίες εμφάνισης είναι στο prompts.md
    img_info = f"\nimage: {image_path}" if image_path else ""
    return f"✅ DRAFT ΑΠΟΘΗΚΕΥΤΗΚΕ.\nmessage: {clean_payload}{img_info}"
@tool
def get_news(topic: str = "Γενικά", limit: int = 10) -> str:
    """Φέρνει ειδήσεις από το Google News με τίτλο, περίληψη, πηγή και link."""
    try:
        topic = (topic or "Γενικά").strip()
        limit = max(1, min(int(limit or 10), 20))
        print(f"\033[96m[Web]: Ανάκτηση ειδήσεων για: {topic}...\033[0m")

        has_greek = any('\u0370' <= c <= '\u03ff' or '\u1f00' <= c <= '\u1fff' for c in topic)
        locale = "el&gl=GR&ceid=GR:el" if has_greek else "en&gl=US&ceid=US:en"

        url = (
            f"https://news.google.com/rss?hl={locale}"
            if topic.lower() in ["γενικά", "general", ""]
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
                line += f"\n   📝 {description}"
            if link:
                line += f"\n   🔗 {link}"
            if source_url:
                line += f"\n   Πηγή: {source_url}"
            news.append(line)

        return "\n\n".join(news) if news else "Δεν βρέθηκαν ειδήσεις."
    except Exception as e:
        return f"News Error: {str(e)}"


@tool
def get_weather_forecast(location: str, days: int = 14) -> str:
    """Επιστρέφει την αναλυτική πρόγνωση καιρού για μια περιοχή (έως 16 ημέρες)."""

    WMO_CODES = {
        0: "☀️ Αίθριος", 1: "🌤 Σχεδόν αίθριος", 2: "⛅ Μερικώς συννεφιά",
        3: "☁️ Συννεφιά", 45: "🌫 Ομίχλη", 48: "🌫 Παγετός",
        51: "🌦 Ψιλόβροχο", 53: "🌦 Βροχή", 55: "🌧 Έντονο ψιλόβροχο",
        61: "🌧 Ελαφριά βροχή", 63: "🌧 Μέτρια βροχή", 65: "🌧 Έντονη βροχή",
        71: "🌨 Ελαφριά χιονόπτωση", 73: "🌨 Χιονόπτωση", 75: "❄️ Έντονη χιονόπτωση",
        80: "🌦 Μπόρες", 81: "🌧 Μέτριες μπόρες", 82: "⛈ Έντονες μπόρες",
        95: "⛈ Καταιγίδα", 96: "⛈ Καταιγίδα με χαλάζι", 99: "⛈ Έντονη καταιγίδα",
    }

    try:
        location = (location or "Θεσσαλονίκη").strip()
        days = max(1, min(int(days or 14), 16))

        geo_url = (
            "https://geocoding-api.open-meteo.com/v1/search"
            f"?name={urllib.parse.quote(location)}&count=1&language=el&format=json"
        )
        geo_resp = requests.get(geo_url, timeout=10).json()

        if "results" not in geo_resp or not geo_resp["results"]:
            return f"Δεν μπόρεσα να βρω την τοποθεσία: {location}"

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
            return "Δεν βρέθηκαν δεδομένα καιρού."

        dates = daily.get("time", [])
        t_max = daily.get("temperature_2m_max", [])
        t_min = daily.get("temperature_2m_min", [])
        precip = daily.get("precipitation_sum", [])
        wcodes = daily.get("weathercode", [])

        count = min(len(dates), len(t_max), len(t_min), len(precip), len(wcodes), days)
        if count == 0:
            return "Δεν βρέθηκαν πλήρη δεδομένα καιρού."

        place_bits = [place_name]
        if admin and admin != place_name:
            place_bits.append(admin)
        if country:
            place_bits.append(country)
        result = f"🌍 Πρόγνωση καιρού για {', '.join(place_bits)} ({count} ημέρες):\n"
        for i in range(count):
            desc = WMO_CODES.get(wcodes[i], f"Κωδικός καιρού {wcodes[i]}")
            rain_info = f"🌧 {precip[i]:.1f}mm" if precip[i] > 0 else ""
            line = f"• {dates[i]}: {desc}  {t_min[i]}°C – {t_max[i]}°C"
            if rain_info:
                line += f"  {rain_info}"
            result += line + "\n"

        return result
    except Exception as e:
        return f"Σφάλμα καιρού: {str(e)}"


@tool
def search_goldmall_offers(query: str) -> str:
    """Deep Scan σε ΟΛΕΣ τις προσφορές του Goldmall χωρίς περιορισμό."""
    search_term = "σινεμά" if any(x in query.lower() for x in ["σινεμά", "ταινία", "ταινιες", "ταινίες"]) else query

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
                return f"Δεν βρέθηκαν αποτελέσματα για '{search_term}'."

            deals = page.locator(".deal-tile").all()[:5]  # max 5 για απόδοση
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

                    noise_words = ["newsletter", "όρους και τις προϋποθέσεις", "T:2310", "info@", "ΠΩΣ ΛΕΙΤΟΥΡΓΕΙ", "ΤΡΟΠΟΙ ΑΓΟΡΑΣ"]
                    schedule_info = []
                    for line in raw_text.split('\n'):
                        clean_line = line.strip()
                        if len(clean_line) > 5 and not any(noise in clean_line for noise in noise_words):
                            if any(char.isdigit() for char in clean_line) or any(
                                day in clean_line for day in ["Σάββατο", "Κυριακή", "Παρασκευή", "Πέμπτη"]
                            ):
                                schedule_info.append(clean_line)

                    description = " | ".join(schedule_info[:5])
                    results.append(f"🎬 **{title_text}**\n📅 {description if description else 'Δείτε το link για ώρες.'}")

                except Exception as e:
                    print(f"\033[91m[DEBUG]: Σφάλμα στην προσφορά {i}: {str(e)}\033[0m")
                    continue
                finally:
                    if detail_page:
                        try:
                            detail_page.close()
                        except:
                            pass

            return "🛒 **Πλήρεις Λεπτομέρειες Goldmall (Θεσσαλονίκη):**\n\n" + "\n\n---\n\n".join(results)

    except Exception as e:
        return f"Γενικό Σφάλμα Goldmall: {str(e)}"
    finally:
        if browser:
            try:
                browser.close()
            except:
                pass


@tool
def execute_local_pipeline(target_name: str = "", message: str = "") -> str:
    """Στέλνει μήνυμα στο Facebook Messenger διαβάζοντας το αποθηκευμένο προσχέδιο.
    ΚΑΛΕΣΕ ΤΟ ΜΟΝΟ αφού ο Λάζαρος επιβεβαιώσει με 'ναι/στείλε'. ΧΩΡΙΣ ΚΑΝΕΝΑ ΟΡΙΣΜΑ."""
    import time
    import json
    import os
    from core.messenger_draft import active_draft_status, inactive_draft_message
    from config import MESSENGER_DRAFT_FILE
    from playwright.sync_api import sync_playwright

    base_dir = os.path.dirname(os.path.abspath(__file__))
    draft_file = MESSENGER_DRAFT_FILE

    # 1. [MASTRO INTERCEPTOR]: Διάβασε το draft
    image_path = ""
    if not target_name or not message:
        is_active, reason, draft = active_draft_status()
        if not is_active:
            return inactive_draft_message(reason)
        target_name = target_name or draft.get("target_name", "")
        message = message or draft.get("message", "")
        image_path = draft.get("image_path", "")
        print(f"\033[93m[Messenger]: Βρέθηκε draft για {target_name}. Εκτέλεση...\033[0m")

    # 2. [MASTRO-ALIAS]: Μετατροπή Ονόματος σε ID
    from memory.vector_store import get_profile_facts
    aliases = {}
    try:
        docs = get_profile_facts(category="contacts", limit=200)
        for d in docs:
            fact = d["fact"]
            if ":" in fact:
                k, v = fact.split(":", 1)
                aliases[k.strip()] = v.strip()
    except Exception as e:
            print(f"⚠️ [Messenger Error]: {e}")

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

    # 3. [SEND]: Απευθείας αποστολή — έγκριση έγινε ήδη από relay_local_payload
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

            print(f"🚀 Απευθείας πλοήγηση στο chat: {chat_url}")
            page.goto(chat_url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(5.0)

            # 4a. [IMAGE ATTACHMENT]: Επισύναψε εικόνα αν υπάρχει
            if image_path and os.path.exists(image_path):
                print(f"\033[96m[Messenger]: Επισύναψη εικόνας: {image_path}\033[0m")
                try:
                    # Messenger έχει hidden file input — το βρίσκουμε και βάζουμε το αρχείο
                    file_input = page.locator('input[type="file"]').first
                    file_input.set_input_files(image_path)
                    # Περιμένουμε να εμφανιστεί preview της εικόνας (max 15s)
                    page.wait_for_selector(
                        'img[src*="blob:"], div[aria-label*="εικόν"], div[aria-label*="photo"], '
                        'div[aria-label*="image"], div[class*="image"], div[class*="photo"]',
                        timeout=15000,
                    )
                    print("\033[92m[Messenger]: Εικόνα επισυνάφθηκε ✓\033[0m")
                    time.sleep(1.0)
                except Exception as img_err:
                    print(f"\033[93m[Messenger]: ⚠️ Αποτυχία επισύναψης εικόνας: {img_err}\033[0m")
                    print("\033[93m[Messenger]: Συνεχίζω με αποστολή μόνο κειμένου.\033[0m")

            # 4b. [SEND TEXT]: Πληκτρολόγηση + Enter
            # Timeout αυξημένο σε 25s — Messenger SPA μερικές φορές αργεί
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
        return f"❌ Σφάλμα Messenger: {str(e)}"
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
    # Αν υπάρχει TRIGGER_PENDING routine (π.χ. "πρωινό μήνυμα Σοφία"),
    # το επιβεβαιώνουμε αυτόματα μετά από επιτυχή αποστολή.
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

    img_suffix = f" (με εικόνα: {os.path.basename(image_path)})" if image_path and os.path.exists(image_path) else ""
    return f"✅ Το μήνυμα στάλθηκε στον/στη {target_name}!{img_suffix}"
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

@tool
def browse_url(url: str) -> str:
    """Ανοίγει μια διεύθυνση URL με browser και επιστρέφει το κείμενο της σελίδας."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                accept_downloads=False
            )
            
            page = context.new_page()
            
            # [MASTRO-FIX]: Αλεξίσφαιρος έλεγχος για το stealth_sync!
            if 'stealth_sync' in globals() and stealth_sync is not None:
                try:
                    if callable(stealth_sync):
                        stealth_sync(page)  # Αν είναι κανονική συνάρτηση
                    elif hasattr(stealth_sync, 'stealth_sync'):
                        stealth_sync.stealth_sync(page)  # Αν είναι module
                except Exception as e:
                    print(f"⚠️ [Web Tool]: Το stealth mode απέτυχε, συνεχίζω κανονικά. ({e})")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(3000)
            except PlaywrightTimeoutError:
                browser.close()
                return f"[WEB_TOOL_ERROR][browse_url][reason=timeout] Η σελίδα '{url}' άργησε υπερβολικά."

            # Αφαιρούμε scripts/styles/banners
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
                return f"[WEB_TOOL_ERROR][browse_url][reason=cloudflare] Το site έχει προστασία και δεν με άφησε να το διαβάσω."

            return f"📄 Περιεχόμενο από {url}:\n\n{clean_text}"

    except Exception as e:
        return f"[WEB_TOOL_ERROR][browse_url][reason=generic] Γενικό σφάλμα στο browse_url: Το εργαλείο απέτυχε ({str(e)})" 
@tool
def duckduckgo_search(query: str) -> str:
    """Αναζήτηση στο διαδίκτυο.
    ΓΙΑ ΣΥΓΚΕΚΡΙΜΕΝΟ URL χρησιμοποίησε ΠΑΝΤΑ το browse_url."""
    from ddgs import DDGS
    from ddgs.exceptions import RatelimitException, TimeoutException, DDGSException

    # backend="auto" (το default) δοκιμάζει sequential/batched ΟΛΑ τα engines (έως 8),
    # κάτι που σε fail-cascades έφτανε 20-30+ δευτ. ανά κλήση. Pin σε 2 γρήγορα,
    # επαληθευμένα backends (verified live: duckduckgo ~1s, google ~0.5s) με 1 fallback.
    backends_to_try = ["duckduckgo", "google"]
    last_error = "άγνωστο σφάλμα"

    for backend in backends_to_try:
        try:
            with DDGS(timeout=8) as ddgs:
                results = list(ddgs.text(query, max_results=5, backend=backend))
            if results:
                output = []
                for r in results:
                    output.append(f"Τίτλος: {r['title']}\nURL: {r['href']}\nΠερίληψη: {r['body']}\n")
                return "\n---\n".join(output)
            last_error = "κενό αποτέλεσμα"
        except RatelimitException:
            last_error = "rate limit"
        except TimeoutException:
            last_error = "timeout"
        except DDGSException as e:
            last_error = str(e)
        except Exception as e:
            last_error = str(e)

    return (
        f"[WEB_TOOL_ERROR][duckduckgo_search]"
        f"[reason={last_error}] "
        f"Η αναζήτηση απέτυχε σε {len(backends_to_try)} backends. "
        "ΜΗΝ ξαναδοκιμάσεις το ίδιο ή παρόμοιο ερώτημα αμέσως — "
        "ενημέρωσε τον χρήστη ότι η web αναζήτηση είναι προσωρινά μη διαθέσιμη."
    )
@tool
def search_supermarket_prices(query: str) -> str:
    """Αναζητά τιμές προϊόντος από όλα τα σούπερ μάρκετ (e-katanalotis.gov.gr).
    Παράδειγμα: 'φακές', 'γάλα', 'ελαιόλαδο'"""
    import requests
    from difflib import SequenceMatcher

    PRICES_URL = "https://warply.s3.amazonaws.com/applications/ed840ad545884deeb6c6b699176797ed/basket-retailers/prices.json?cid=1779969600000"

    try:
        r = requests.get(PRICES_URL, timeout=30)
        data = r.json()
        result = data['context']['MAPP_PRODUCTS']['result']
        merchants = {m['merchant_uuid']: m['display_name'] for m in result['merchants']}
        products = result['products']

        # Fuzzy search — αφαίρεση τόνων για σωστό matching
        query_clean = remove_accents(query).upper()
        matches = []
        for p in products:
            name = p.get('name', '')
            if query_clean in remove_accents(name).upper():
                matches.append(p)

        if not matches:
            return f"❌ Δεν βρέθηκε '{query}' στο e-katanalotis."

        # Κράτα τα 5 πιο σχετικά
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

        return "\n\n".join(output) if output else "❌ Δεν βρέθηκαν τιμές."

    except Exception as e:
        return f"⚠️ Σφάλμα: {str(e)}"
@tool
def search_google_places(query: str, location: str = "Thessaloniki") -> str:
    """
    Αναζητά εστιατόρια, καφέ και μέρη για έξοδο μέσω Google Places API (New).
    Επιστρέφει όνομα, βαθμολογία, διεύθυνση, τύπο, τηλέφωνο, website, delivery και reviews.
    """
    import requests
    import os
    import time
    import json
    from config import GPS_STORAGE_FILE
    profile = _build_places_query_profile(query)
    
    # [MASTRO-GPS-INTERCEPTOR]
    if "κοντά" in query.lower() or location == "current":
        if os.path.exists(GPS_STORAGE_FILE):
            try:
                with open(GPS_STORAGE_FILE, "r") as f:
                    gps = json.load(f)
                    # Αν το στίγμα είναι φρέσκο (τελευταία 24ωρα)
                    if time.time() - gps['timestamp'] < 86400:
                        location = f"{gps['lat']},{gps['lon']}"
                        print(f"📍 [Web Tool]: Χρήση Live GPS στίγματος: {location}")
            except Exception as e:
                print(f"⚠️ [Places GPS]: {e}")
            
    api_key = os.getenv("GOOGLE_PLACES_API_KEY", "")
    if not api_key:
        return "❌ Λείπει το GOOGLE_PLACES_API_KEY από το .env"

    search_url = "https://places.googleapis.com/v1/places:searchText"

    # [MASTRO-UPGRADE]: Προσθέσαμε Phone, Website, Takeout, Delivery, DineIn και Reviews στο FieldMask
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

    # [MASTRO-FIX]: GPS coords → locationBias (σωστός τρόπος, όχι text append)
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
            return f"❌ Δεν βρέθηκαν αποτελέσματα για '{query}' στην {location}."

        ranked_places = sorted(
            places,
            key=lambda place: _score_place_match(place, profile),
            reverse=True,
        )[:3]

        # ── Μορφοποίηση αποτελεσμάτων ─────────────────────────
        price_map = {
            "PRICE_LEVEL_FREE": "Δωρεάν",
            "PRICE_LEVEL_INEXPENSIVE": "€",
            "PRICE_LEVEL_MODERATE": "€€",
            "PRICE_LEVEL_EXPENSIVE": "€€€",
            "PRICE_LEVEL_VERY_EXPENSIVE": "€€€€"
        }

        lines = [f"📍 Αποτελέσματα για '{query}' — {location}:\n"]

        for i, place in enumerate(ranked_places, 1):
            name = place.get("displayName", {}).get("text", "Άγνωστο")
            rating = place.get("rating", "—")
            votes = place.get("userRatingCount", 0)
            address = place.get("formattedAddress", "Χωρίς διεύθυνση")
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
                hours_info = " · ✅ Ανοιχτό"
            elif opening.get("openNow") is False:
                hours_info = " · 🔴 Κλειστό"

            price_str = f" · {price}" if price else ""
            rating_str = f"⭐ {rating} ({votes} κριτικές)" if rating != "—" else "Χωρίς βαθμολογία"
            type_str = f" · {ptype}" if ptype else ""
            
            contact_str = ""
            if phone: contact_str += f"   📞 {phone}\n"
            if website: contact_str += f"   🌐 <a href='{website}'>Website Μαγαζιού</a>\n"
            
            services_str = f"   🛵 [{', '.join(services)}]\n" if services else ""
            review_str = f"   💬 \"{review_text}\"\n" if review_text else ""

            lines.append(
                f"{i}. <b>{name}</b>{price_str}\n"
                f"   {rating_str}{type_str}{hours_info}\n"
                f"   📌 {address}\n"
                f"{contact_str}"
                f"{services_str}"
                f"{review_str}"
                f"   🗺️ <a href='{maps_url}'>Άνοιγμα στο Google Maps</a>\n"
                f"   🧭 Match: {match_score}\n"
            )

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Σφάλμα: {str(e)}"

@tool
def get_navigation_info(destination: str) -> str:
    """Παρέχει κλικαριστά links για χάρτη και πλοήγηση από Piston 7."""
    home_base = "Piston 7, Thessaloniki"
    dest_clean = urllib.parse.quote_plus(destination)
    home_clean = urllib.parse.quote_plus(home_base)

    search_url = f"https://www.google.com/maps/search/?api=1&query={dest_clean}"
    directions_url = f"https://www.google.com/maps/dir/?api=1&origin={home_clean}&destination={dest_clean}"

    return (
        f"📍 <b>Τοποθεσία:</b> {destination}\n\n"
        f"🔗 <a href='{search_url}'>Προβολή στον Χάρτη</a>\n"
        f"🌐 {search_url}\n\n"
        f"🚗 <a href='{directions_url}'>Οδηγίες πλοήγησης από Piston 7</a>\n"
        f"🛣️ {directions_url}"
    )
