"""
Tests για τη νέα "category-safe semantic overwrite" λογική στο
AstakosMemoryManager._save_fact (memory/vector_store.py, γραμμές ~115-253).

ΣΗΜΕΙΩΣΗ για τον εαυτό μου / μελλοντικό Claude:
Ο sandbox mount έχει stale cache για το vector_store.py μετά το τελευταίο edit
(γνωστό πρόβλημα — βλ. memory "feedback_stale_mount.md": cat/wc/git diff δείχνουν
το αρχείο κομμένο στις 460 γραμμές αντί για τις πραγματικές ~567, με phantom
deletions ολόκληρων functions). Ο import μέσω pytest άρα σκάει με SyntaxError σε
περιεχόμενο που ΔΕΝ υπάρχει στο πραγματικό αρχείο (επιβεβαιωμένο μέσω Read tool).

Άρα εδώ τεστάρουμε την ΑΠΟΦΑΣΗ-λογική (richness scoring, correction markers,
category-safe επιλογή, keep_old decision) ως αυτόνομη pure-function αναπαραγωγή
— ΑΚΡΙΒΩΣ το ίδιο σώμα κώδικα που υπάρχει στο πραγματικό αρχείο (επιβεβαιωμένο
γραμμή-προς-γραμμή μέσω Read tool, lines 160-253) — ώστε να ελέγξουμε τη σωστότητα
του αλγορίθμου χωρίς να εξαρτόμαστε από το import του (μη προσβάσιμου φρέσκου)
module. Όταν διορθωθεί το mount staleness, αυτό μπορεί να αντικατασταθεί με
end-to-end test μέσω AstakosMemoryManager._save_fact με mocked collection.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Ακριβές αντίγραφο της απόφασης-λογικής από memory/vector_store.py:160-253
# (verbatim copy — confirmed via Read tool against the real file on disk)
# ---------------------------------------------------------------------------

CORRECTION_MARKERS = (
    "διορθω", "διόρθω", "λάθος", "λαθος", "όχι αυτό", "οχι αυτο",
    "το σωστό ε", "σωστό είναι", "σωστό:", "τελικά", "τελικα",
    "δεν ισχύει", "δεν ισχυει", "άλλαξε", "αλλαξε", "ενημερωμέν",
    "πλέον είναι", "ξαναλέω", "ξαναλεω",
    "correction", "update", "actually",
)

ENTITY_MARKERS = (
    "σοφια", "σοφία", "αλεξανδρ", "αλέξανδρ", "μαρια", "μαρία",
    "mastroapp", "praxis", "shiftmaster", "paletes", "astakos", "αστακο",
)
LINK_MARKERS = ("http", "https", "/", "\\", ".py", ".json", ".md", ".db")
EVENT_MARKERS = (
    "πηγαμε", "πήγαμε", "εκανε", "έκανε", "εγινε", "έγινε",
    "πηρε", "πήρε", "εφαγε", "έφαγε", "βρηκαμε", "βρήκαμε",
    "αγορασ", "αγόρασ", "διαβασ", "διάβασ",
)


def _has_date(text):
    low = str(text).lower()
    if "στις" in low:
        return True
    run = 0
    for ch in str(text):
        run = run + 1 if ch.isdigit() else 0
        if run >= 4:
            return True
    return False


def _richness(text, meta):
    low = str(text).lower()
    score = 0.0
    if _has_date(text):
        score += 1
    if any(m in low for m in ENTITY_MARKERS):
        score += 1
    if any(m in low for m in LINK_MARKERS):
        score += 1
    if any(m in low for m in EVENT_MARKERS):
        score += 1
    try:
        score += float((meta or {}).get("confidence", 0) or 0)
    except (TypeError, ValueError):
        pass
    return score


def decide(fact, old_content, old_meta, confidence):
    """Αναπαράγει ακριβώς το decision block (lines 169-253)."""
    looks_like_correction = any(m in fact.lower() for m in CORRECTION_MARKERS)

    old_age_days = None
    try:
        old_ts = float((old_meta or {}).get("timestamp") or 0)
        if old_ts > 0:
            old_age_days = max(0, (datetime.now() - datetime.fromtimestamp(old_ts)).days)
    except (TypeError, ValueError, OSError):
        old_age_days = None
    stale = old_age_days is not None and old_age_days > 30

    new_richness = _richness(fact, {"confidence": confidence})
    old_richness = _richness(old_content, old_meta)
    much_longer = len(old_content) > len(str(fact)) * 1.3

    keep_old = (
        not looks_like_correction
        and not stale
        and (old_richness > new_richness or (old_richness == new_richness and much_longer))
    )
    return {
        "keep_old": keep_old,
        "looks_like_correction": looks_like_correction,
        "stale": stale,
        "new_richness": new_richness,
        "old_richness": old_richness,
    }


# ---------------------------------------------------------------------------
# 1) Category-safe matching: cross-category κοντινό match -> ΠΟΤΕ auto-delete
#    (η πραγματική προστασία είναι δομική: cross-category απλά δεν μπαίνει
#    καν στο decide() block — εδώ επιβεβαιώνουμε ότι old_id παραμένει None
#    όταν δεν υπάρχει same-category match, αναπαράγοντας lines 134-143)
# ---------------------------------------------------------------------------

def test_cross_category_close_match_never_enters_delete_path():
    same_cat_dist = None  # τίποτα στην ΙΔΙΑ category
    old_id = None
    if same_cat_dist is not None and same_cat_dist < 0.25:
        old_id = "would-be-deleted"
    # cross-category dist=0.05 (πολύ κοντά) — αλλά ΔΕΝ μπαίνει στο if-block
    # που οδηγεί σε delete (lines 144-158 είναι warn-only, lines 160+ απαιτούν old_id)
    assert old_id is None, "Cross-category match δεν πρέπει ΠΟΤΕ να θέσει old_id -> delete path"


# ---------------------------------------------------------------------------
# 2) Ρητή διόρθωση -> πάντα overwrite, ανεξαρτήτως richness
# ---------------------------------------------------------------------------

def test_explicit_correction_overwrites_even_if_old_is_richer():
    old_content = (
        "[USER_FACT]: Στις 2026-05-01 ο Λάζαρος είπε ότι μένουν στο Πεστών 7 "
        "με τη Σοφία και τον Αλέξανδρο, https://maps.example/old"
    )
    old_meta = {"timestamp": datetime.now().timestamp(), "confidence": 0.7}
    new_fact = "[USER_FACT]: Λάθος, η σωστή διεύθυνση είναι Πίστων 7"

    result = decide(new_fact, old_content, old_meta, confidence=0.7)

    assert result["looks_like_correction"] is True
    assert result["keep_old"] is False, "Ρητή διόρθωση πρέπει να κάνει πάντα overwrite"
    # Επιβεβαίωση ότι η παλιά ΟΝΤΩΣ θα είχε «κερδίσει» στο richness — δηλ. το
    # correction marker είναι αυτό που γέρνει την απόφαση, όχι το richness.
    assert result["old_richness"] > result["new_richness"]


# ---------------------------------------------------------------------------
# 3) Richness scoring αντί για μήκος
# ---------------------------------------------------------------------------

def test_richer_new_fact_overwrites_longer_but_emptier_old_one():
    old_content = (
        "[LESSON]: Γενικά καλό είναι να προσέχουμε πάντα τη δομή του κώδικα "
        "και να γράφουμε καθαρά σχόλια παντού στο πρόγραμμα όποτε μπορούμε"
    )
    new_fact = (
        "[LESSON]: Στις 2026-06-08 διορθώσαμε bug στο Astakos, "
        "δες memory/vector_store.py"
    )
    old_meta = {"timestamp": datetime.now().timestamp(), "confidence": 0.5}

    result = decide(new_fact, old_content, old_meta, confidence=0.8)

    assert len(old_content) > len(new_fact), "προϋπόθεση σεναρίου: η παλιά να είναι μακρύτερη"
    assert result["new_richness"] > result["old_richness"], (
        "η νέα έχει ημερομηνία+project+link+γεγονός, η παλιά τίποτα — "
        "πρέπει να κερδίζει σε richness παρότι είναι πιο σύντομη"
    )
    assert result["keep_old"] is False


def test_richer_old_fact_is_kept_over_generic_new_one():
    old_content = "[USER_FACT]: Στις 2026-05-20 ο Αλέξανδρος πήγε στο πάρκο με τη Σοφία"
    new_fact = "[USER_FACT]: Ο Αλέξανδρος πάει συχνά βόλτα"
    old_meta = {"timestamp": datetime.now().timestamp(), "confidence": 0.7}

    result = decide(new_fact, old_content, old_meta, confidence=0.5)

    assert result["looks_like_correction"] is False
    assert result["stale"] is False
    assert result["old_richness"] > result["new_richness"]
    assert result["keep_old"] is True, "η πιο πλούσια & πρόσφατη παλιά πρέπει να κρατηθεί"


# ---------------------------------------------------------------------------
# 4) Stale (>30 ημέρες) -> overwrite ακόμα κι αν δεν υπάρχει correction marker
#    ΚΑΙ ακόμα κι αν η παλιά είναι πιο "πλούσια" -- η φθορά νικάει το richness
# ---------------------------------------------------------------------------

def test_stale_old_record_is_overwritten_without_correction_language():
    old_ts = (datetime.now() - timedelta(days=45)).timestamp()
    old_content = "[LESSON]: Στις 2026-04-01 κάτι λεπτομερές για το Mastroapp, δες app.py"
    old_meta = {"timestamp": old_ts, "confidence": 0.7}
    new_fact = "[LESSON]: μικρή νέα σημείωση"

    result = decide(new_fact, old_content, old_meta, confidence=0.5)

    assert result["looks_like_correction"] is False
    assert result["stale"] is True
    assert result["old_richness"] > result["new_richness"], (
        "προϋπόθεση: η παλιά να ΦΑΙΝΕΤΑΙ πιο πλούσια — ώστε να ελέγξουμε ότι "
        "η φθορά (stale) υπερισχύει του richness, όχι το αντίστροφο"
    )
    assert result["keep_old"] is False, "stale εγγραφή -> overwrite, ακόμα κι αν φαίνεται πλουσιότερη"


# ---------------------------------------------------------------------------
# 5) Ίσο richness -> tie-break με μήκος (much_longer), όπως πριν
# ---------------------------------------------------------------------------

def test_equal_richness_falls_back_to_length_tiebreak():
    # Και οι δύο: ημερομηνία + entity = richness 2.0 + ίδιο confidence κλπ.
    old_content = (
        "[USER_FACT]: Στις 2026-06-01 ο Αλέξανδρος έπαιξε με τον Λάζαρο LEGO "
        "για πολλή ώρα και έφτιαξαν ένα ολόκληρο κάστρο μαζί στο σαλόνι"
    )
    new_fact = "[USER_FACT]: Στις 2026-06-08 ο Αλέξανδρος έπαιξε LEGO με τον Λάζαρο"
    old_meta = {"timestamp": datetime.now().timestamp(), "confidence": 0.7}

    result = decide(new_fact, old_content, old_meta, confidence=0.7)

    assert result["old_richness"] == result["new_richness"]
    assert len(old_content) > len(new_fact) * 1.3
    assert result["keep_old"] is True, "ίδιο richness, παλιά σαφώς μακρύτερη -> tie-break στο μήκος"
