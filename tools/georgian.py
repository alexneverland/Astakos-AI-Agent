"""
tools/georgian.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Greek ↔ Georgian translation tool
with voice playback via edge-tts.

Uses the unofficial Google Translate API
(client=gtx) — without an API key.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import io
import requests

# ── Georgian alphabet (Mkhedruli) → Latin phonetics ──────────────────────
_KA_PHONETICS: dict[str, str] = {
    "ა": "a",  "ბ": "b",  "გ": "g",  "დ": "d",  "ე": "e",
    "ვ": "v",  "ზ": "z",  "თ": "th", "ი": "i",  "კ": "k'",
    "ლ": "l",  "მ": "m",  "ნ": "n",  "ო": "o",  "პ": "p'",
    "ჟ": "zh", "რ": "r",  "ს": "s",  "ტ": "t'", "უ": "u",
    "ფ": "p",  "ქ": "k",  "ღ": "gh", "ყ": "q'", "შ": "sh",
    "ჩ": "ch", "ც": "ts", "ძ": "dz", "წ": "ts'","ჭ": "ch'",
    "ხ": "kh", "ჯ": "j",  "ჰ": "h",
}


def _to_phonetic(text: str) -> str:
    """Translates Georgian text into Latin phonetics."""
    return "".join(_KA_PHONETICS.get(c, c) for c in text)


def _is_georgian(text: str) -> bool:
    """True if the text contains Georgian characters (Mkhedruli U+10D0–U+10FF)."""
    return any("ა" <= c <= "ჿ" for c in text)


def translate(text: str, *, src: str = "auto", tgt: str = "ka") -> dict[str, str]:
    """
    Translates text via Google Translate (unofficial, without key).

    With src="auto":
      • If the text is Georgian  → translates to Greek (ka→el)
      • Otherwise                → translates to Georgian (el→ka)

    Returns:
        {
          "translated": str,   # translated text
          "phonetic":   str,   # Latin phonetics (only if tgt=="ka")
          "src":        str,   # source language used
          "tgt":        str,   # target language used
        }
    """
    if src == "auto":
        src = "ka" if _is_georgian(text) else "el"
        tgt = "el" if src == "ka" else "ka"
    else:
        # Forced direction: tgt = opposite of src
        tgt = "el" if src == "ka" else "ka"

    resp = requests.get(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": src, "tl": tgt, "dt": "t", "q": text},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    translated = "".join(part[0] for part in data[0] if part and part[0])
    phonetic = _to_phonetic(translated) if tgt == "ka" else ""

    return {"translated": translated, "phonetic": phonetic, "src": src, "tgt": tgt}


_EDGE_VOICES: dict[str, str] = {
    "ka": "ka-GE-EkaNeural",   # Georgian female neural voice
    "el": "el-GR-NestorasNeural",
}


async def _tts_edge(text: str, voice: str) -> bytes:
    """Async helper: generates audio via edge-tts."""
    import edge_tts

    buf = io.BytesIO()
    communicate = edge_tts.Communicate(text, voice)
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    buf.seek(0)
    return buf.read()


def tts_audio(text: str, lang: str = "ka") -> bytes:
    """
    Generates audio bytes via edge-tts.
    Georgian: ka-GE-EkaNeural (Microsoft neural voice — supports ka).
    """
    import asyncio

    voice = _EDGE_VOICES.get(lang, "ka-GE-EkaNeural")
    return asyncio.run(_tts_edge(text, voice))


# ── Quick phrases (pre-translated) ─────────────────────────────────────────
QUICK_PHRASES: dict[str, list[dict[str, str]]] = {
    "💕 Αγάπη": [
        {"el": "Σ'αγαπώ",              "ka": "გიყვარხარ",                    "ph": "giq'varxar"},
        {"el": "Μου λείπεις",           "ka": "მენატრები",                    "ph": "menat'rebi"},
        {"el": "Είσαι όμορφη",          "ka": "ლამაზი ხარ",                   "ph": "lamazi xar"},
        {"el": "Καλημέρα αγάπη μου",    "ka": "დილა მშვიდობისა სიყვარულო",   "ph": "dila mshvidobisa siq'varulo"},
        {"el": "Καληνύχτα αγάπη μου",   "ka": "ღამე მშვიდობისა სიყვარულო",   "ph": "ghame mshvidobisa siq'varulo"},
        {"el": "Σε χρειάζομαι",         "ka": "მჭირდები",                     "ph": "mch'irdbi"},
        {"el": "Σκέφτομαι εσένα",       "ka": "შენზე ვფიქრობ",               "ph": "shenze vpik'rob"},
    ],
    "🏠 Σπίτι": [
        {"el": "Φαΐ έτοιμο",            "ka": "საჭმელი მზადაა",               "ph": "sachmeli mzadaa"},
        {"el": "Έλα να φάμε",           "ka": "მოდი ვიჭამოთ",                "ph": "modi vichamot'"},
        {"el": "Πού είσαι;",            "ka": "სად ხარ?",                     "ph": "sad xar?"},
        {"el": "Έρχομαι σπίτι",         "ka": "სახლში მოვდივარ",              "ph": "saxlshi movdivar"},
        {"el": "Τηλεφώνησέ μου",        "ka": "დამირეკე",                     "ph": "damireke"},
        {"el": "Θα αργήσω",             "ka": "დავაგვიანდები",                "ph": "davagviandebi"},
        {"el": "Κρύωσε, κλείσε παράθυρο","ka": "ცივა, დახურე ფანჯარა",       "ph": "tsiva, daxure panjara"},
    ],
    "👶 Αλέξανδρος": [
        {"el": "Πάμε για ύπνο",         "ka": "წავიძინოთ",                    "ph": "ts'avidzinot'"},
        {"el": "Φάε το φαγητό σου",     "ka": "შეჭამე საჭმელი",              "ph": "shechame sachmeli"},
        {"el": "Μπράβο!",               "ka": "კარგი ბიჭი!",                  "ph": "k'argi bichi!"},
        {"el": "Σταμάτα!",              "ka": "გაჩერდი!",                     "ph": "gacherdi!"},
        {"el": "Έλα εδώ",               "ka": "მოდი აქ",                      "ph": "modi ak'"},
        {"el": "Ησύχασε",               "ka": "დამშვიდდი",                    "ph": "damshviddi"},
        {"el": "Πλύνε τα χέρια σου",    "ka": "ხელები დაიბანე",              "ph": "xelebi daibane"},
    ],
    "😄 Καθημερινά": [
        {"el": "Ναι",                   "ka": "კი",                           "ph": "k'i"},
        {"el": "Όχι",                   "ka": "არა",                          "ph": "ara"},
        {"el": "Ευχαριστώ",             "ka": "მადლობა",                      "ph": "madloba"},
        {"el": "Συγγνώμη",              "ka": "ბოდიში",                       "ph": "bodishi"},
        {"el": "Εντάξει",               "ka": "კარგი",                        "ph": "k'argi"},
        {"el": "Δεν ξέρω",              "ka": "არ ვიცი",                      "ph": "ar vitsi"},
        {"el": "Κουράστηκα",            "ka": "დავიღალე",                     "ph": "davighale"},
        {"el": "Πεινάω",                "ka": "მშია",                         "ph": "mshia"},
    ],
}


def phrases_message() -> str:
    """Returns a Telegram-ready text with all the quick phrases."""
    lines = ["🇬🇪 <b>Γρήγορες Φράσεις Ελληνικά → Γεωργιανά</b>\n"]
    for cat, phrases in QUICK_PHRASES.items():
        lines.append(f"<b>{cat}</b>")
        for p in phrases:
            lines.append(f"• {p['el']} → <code>{p['ka']}</code>")
            lines.append(f"  <i>📢 {p['ph']}</i>")
        lines.append("")
    lines.append("Tip: <code>/g &lt;κείμενο&gt;</code> για ελεύθερη μετάφραση + ήχο")
    return "\n".join(lines)
