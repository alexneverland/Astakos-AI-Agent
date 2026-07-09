import os
from langchain_core.tools import tool
from config import BASE_DIR

VENDOR_SKILLS_DIR = os.path.join(BASE_DIR, "vendor", "agent-skills", "skills")

@tool
def list_agent_skills() -> str:
    """
    Επιστρέφει μια λίστα με όλα τα διαθέσιμα 'Agent Skills' (του Addy Osmani).
    Χρησιμοποίησε αυτήν την εντολή για να δεις τι skills υπάρχουν πριν ζητήσεις να διαβάσεις κάποιο.
    """
    if not os.path.exists(VENDOR_SKILLS_DIR):
        return "⚠️ Σφάλμα: Ο φάκελος vendor/agent-skills/skills δεν βρέθηκε."
    
    try:
        skills = []
        for d in os.listdir(VENDOR_SKILLS_DIR):
            skill_path = os.path.join(VENDOR_SKILLS_DIR, d)
            if os.path.isdir(skill_path) and os.path.exists(os.path.join(skill_path, "SKILL.md")):
                skills.append(d)
        
        if not skills:
            return "Δεν βρέθηκαν Agent Skills."
            
        return "Διαθέσιμα Agent Skills:\n" + "\n".join(f"- {s}" for s in sorted(skills))
    except Exception as e:
        return f"⚠️ Σφάλμα ανάγνωσης: {str(e)}"

@tool
def read_agent_skill(skill_name: str) -> str:
    """
    Διαβάζει τους κανόνες και το workflow ενός συγκεκριμένου 'Agent Skill' (του Addy Osmani).
    Πέρνα ακριβώς το όνομα του skill (π.χ. 'test-driven-development').
    Ακολούθησε τις οδηγίες του skill πιστά κατά την εκτέλεση του task σου.
    """
    skill_name = skill_name.strip()
    skill_file = os.path.join(VENDOR_SKILLS_DIR, skill_name, "SKILL.md")
    
    if not os.path.exists(skill_file):
        return f"⚠️ Σφάλμα: Το skill '{skill_name}' δεν βρέθηκε. Δοκίμασε το list_agent_skills() για να δεις τα διαθέσιμα."
        
    try:
        with open(skill_file, "r", encoding="utf-8") as f:
            content = f.read()
        return f"=== KANONEΣ / WORKFLOW ΓΙΑ ΤΟ SKILL: {skill_name} ===\n\n{content}"
    except Exception as e:
        return f"⚠️ Σφάλμα ανάγνωσης του αρχείου SKILL.md: {str(e)}"
