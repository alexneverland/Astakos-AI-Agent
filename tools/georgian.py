"""
tools/georgian.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Εργαλείο μετάφρασης Ελληνικά ↔ Γεωργιανά
με φωνητική αναπαραγωγή (gTTS).

Χρησιμοποιεί Google Translate unofficial API
(client=gtx) — χωρίς API key.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import io
import requests

# ── Γεωργιανό αλφάβητο (Mkhedruli) → Λατινική φωνητική ──────────────────────
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
    """Μετατρέπει Γεωργιανό κείμενο σε Λατινική φωνητική."""
    return "".join(_KA_PHONETICS.get(c, c) for c in text)


def _is_georgian(text: str) -> bool:
    """True αν το κείμενο περιέχει Γεωργιανούς χαρακτήρες (Mkhedruli U+10D0–U+10FF)."""
    return any("ა" <= c <= "ჿ" for c in text)


def translate(text: str, *, src: str = "auto", tgt: str = "ka") -> dict[str, str]:
    """
    Μεταφράζει κείμενο μέσω Google Translate (unofficial, χωρίς key).

    Με src="auto":
      • Αν το κείμενο είναι Γεωργιανό  → μεταφράζει σε Ελληνικά (ka→el)
      • Αλλιώς                          → μεταφράζει σε Γεωργιανά (el→ka)

    Returns:
        {
          "translated": str,   # μεταφρασμένο κείμενο
          "phonetic":   str,   # Latin phonetics (μόνο αν tgt=="ka")
          "src":        str,   # γλώσσα πηγής που χρησιμοποιήθηκε
          "tgt":        str,   # γλώσσα στόχος που χρησιμοποιήθηκε
        }
    """
    if src == "auto":
        src = "ka" if _is_georgian(text) else "el"
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


def tts_audio(text: str, lang: str = "ka") -> bytes:
    """
    Παράγει MP3 bytes χρησιμοποιώντας Google Translate TTS (unofficial endpoint).
    Υποστηρίζει Γεωργιανά (ka) — το gTTS ΔΕΝ υποστηρίζει ka.
    """
    resp = requests.get(
        "https://translate.google.com/translate_tts",
        params={"ie": "UTF-8", "q": text, "tl": lang, "client": "tw-ob", "ttsspeed": "0.8"},
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.content


# ── Γρήγορες φράσεις (pre-translated) ───────────────────────────────────────
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
    """Επιστρέφει ένα Telegram-ready κείμενο με όλες τις γρήγορες φράσεις."""
    lines = ["🇬🇪 *Γρήγορες Φράσεις Ελληνικά → Γεωργιανά*\n"]
    for cat, phrases in QUICK_PHRASES.items():
        lines.append(f"*{cat}*")
        for p in phrases:
            # escape MarkdownV2 special chars in phonetic
            lines.append(f"• {p['el']} → `{p['ka']}`")
            lines.append(f"  _📢 {p['ph']}_")
        lines.append("")
    lines.append("_Tip: /georgian \\<κείμενο\\> για ελεύθερη μετάφραση \\+ ήχο_")
    return "\n".join(lines)
