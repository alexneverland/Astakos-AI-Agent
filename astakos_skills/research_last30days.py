import os
import subprocess
from langchain_core.tools import tool
from config import BASE_DIR


@tool
def research_last30days(topic: str) -> str:
    """
    Διεξάγει βαθιά έρευνα στο web για οποιοδήποτε θέμα, σαρώνοντας πηγές όπως Reddit, X (Twitter), 
    YouTube, Hacker News και Polymarket, αναζητώντας δεδομένα μόνο από τις τελευταίες 30 μέρες.
    Επιστρέφει μια συλλογική ανάλυση (synthesis) της κοινότητας με βάση τον αριθμό engagements (upvotes, likes κλπ).
    """
    script_path = os.path.join(BASE_DIR, "vendor", "last30days-skill", "skills", "last30days", "scripts", "last30days.py")
    
    if not os.path.exists(script_path):
        return f"Σφάλμα: Δεν βρέθηκε το script στο '{script_path}'. Εγκαταστήστε το στο vendor directory."

    try:
        # Τρέχουμε την εντολή και επιστρέφουμε το stdout σε μορφή compact md για πιο εύκολο parsing από τον Agent.
        result = subprocess.run(
            ["python", script_path, "--emit", "md", topic],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=BASE_DIR,
            timeout=900,
        )

        if result.returncode != 0:
            return f"Σφάλμα κατά την εκτέλεση του last30days-skill:\n{result.stderr}"
        
        # Αν η εκτέλεση πέτυχε, επιστρέφουμε το αποτέλεσμα.
        # Μπορεί το stdout να έχει warnings κτλ, αλλά συνήθως το output είναι markdown text.
        return result.stdout.strip()
        
    except Exception as e:
        return f"Απρόσμενο σφάλμα κατά την έρευνα (last30days-skill): {str(e)}"
