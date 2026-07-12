import os
from langchain_core.tools import tool
from config import BASE_DIR
from core.i18n import t

VENDOR_SKILLS_DIR = os.path.join(BASE_DIR, "vendor", "agent-skills", "skills")

@tool
def list_agent_skills() -> str:
    """
    Returns a list of all available 'Agent Skills' (by Addy Osmani).
    Use this command to see what skills exist before requesting to read one.
    """
    if not os.path.exists(VENDOR_SKILLS_DIR):
        return t("skills.read_agent_skill.no_folder")
    
    try:
        skills = []
        for d in os.listdir(VENDOR_SKILLS_DIR):
            skill_path = os.path.join(VENDOR_SKILLS_DIR, d)
            if os.path.isdir(skill_path) and os.path.exists(os.path.join(skill_path, "SKILL.md")):
                skills.append(d)
        
        if not skills:
            return t("skills.read_agent_skill.none_found")
            
        return t("skills.read_agent_skill.available") + "\n".join(f"- {s}" for s in sorted(skills))
    except Exception as e:
        return t("skills.read_agent_skill.msg_read_err", e=str(e))

@tool
def read_agent_skill(skill_name: str) -> str:
    """
    Reads the rules and workflow of a specific 'Agent Skill' (by Addy Osmani).
    Pass exactly the name of the skill (e.g., 'test-driven-development').
    Follow the skill's instructions faithfully during the execution of your task.
    """
    skill_name = skill_name.strip()
    skill_file = os.path.join(VENDOR_SKILLS_DIR, skill_name, "SKILL.md")
    
    if not os.path.exists(skill_file):
        return t("skills.read_agent_skill.msg_not_found_2", skill=skill_name)
        
    try:
        with open(skill_file, "r", encoding="utf-8") as f:
            content = f.read()
        return t("skills.read_agent_skill.msg_workflow", skill=skill_name, content=content)
    except Exception as e:
        return t("skills.read_agent_skill.msg_md_err", e=str(e))
