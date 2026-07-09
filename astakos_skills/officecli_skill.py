import os
import subprocess
from langchain_core.tools import tool
from config import BASE_DIR

@tool
def run_officecli(command: str) -> str:
    """
    Εκτελεί εντολές στο OfficeCLI για δημιουργία και επεξεργασία αρχείων Word (.docx), Excel (.xlsx), και PowerPoint (.pptx).
    Το OfficeCLI υποστηρίζει templates, rendering HTML σε docx, formulas στο Excel κ.α.

    ΑΠΑΓΟΡΕΥΕΤΑΙ: Μην χρησιμοποιείς τα παλιά create_file_tool ή generate_word_doc για Office αρχεία. 
    Χρησιμοποίησε αυτό το tool για απλές μετατροπές ή templates. ΑΝ ΟΜΩΣ χρειάζεται περίπλοκη δομή (π.χ. custom ημερολόγια, ειδικά κελιά με openpyxl/python-docx), ΕΠΙΤΡΕΠΕΤΑΙ να χρησιμοποιήσεις python (run_terminal_command ή run_code) παρακάμπτοντας αυτό το tool.
    ΠΑΝΤΑ να δημιουργείς ή να σώζεις τα αρχεία μέσα στον φάκελο:
    C:/astakos_v2/outputs/
    Ώστε το drive_manager και τα Web UIs να τα βρίσκουν!
    
    Παραδείγματα:
    - officecli add deck.pptx / --type slide --title "Intro"
    - officecli render template.docx data.json --out C:/astakos_v2/outputs/report.docx
    - officecli formula calc C:/astakos_v2/outputs/data.xlsx
    
    Αν το command ξεκινάει με 'officecli ', θα αντικατασταθεί με το πλήρες path του εκτελέσιμου.
    """
    officecli_path = os.path.join(BASE_DIR, "vendor", "officecli", "officecli.exe")
    outputs_dir = os.path.join(BASE_DIR, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)
    
    if not os.path.exists(officecli_path):
        return f"❌ Το OfficeCLI δεν βρέθηκε στο {officecli_path}. Παρακαλώ κατεβάστε το πρώτα."
    
    # Αφαίρεση του 'officecli ' από την αρχή αν υπάρχει, για να βάλουμε το δικό μας path
    if command.startswith("officecli "):
        command = command[10:]
        
    full_command = f'"{officecli_path}" {command}'
    
    try:
        # Εκτελούμε την εντολή μέσα στον φάκελο outputs για μεγαλύτερη ασφάλεια
        result = subprocess.run(
            full_command, 
            shell=True, 
            cwd=outputs_dir, 
            capture_output=True, 
            text=True, 
            encoding='utf-8', 
            errors='replace'
        )
        if result.returncode == 0:
            return f"✅ OfficeCLI Εκτελέστηκε Επιτυχώς.\nΈξοδος:\n{result.stdout.strip()}"
        else:
            return f"❌ Σφάλμα OfficeCLI (Exit Code: {result.returncode}).\nΣφάλμα:\n{result.stderr.strip()}"
    except Exception as e:
        return f"❌ Exception κατά την εκτέλεση του OfficeCLI: {str(e)}"
