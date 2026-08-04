import os
from pathlib import Path
import threading
import time

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Astakos Setup Wizard")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "api", "static")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

ENV_FILE = os.path.join(BASE_DIR, ".env")
PERSONA_FILE = os.path.join(BASE_DIR, "persona.md")
PERSONA_EXAMPLE = os.path.join(BASE_DIR, "persona.md.example")
INTENTS_FILE = os.path.join(BASE_DIR, "astakos_custom_intents.json")
INTENTS_EXAMPLE = os.path.join(BASE_DIR, "astakos_custom_intents.json.example")
ROUTINES_FILE = os.path.join(BASE_DIR, "astakos_routines.json")
ROUTINES_EXAMPLE = os.path.join(BASE_DIR, "astakos_routines.json.example")
SETUP_GUIDE_FILE = os.path.join(BASE_DIR, "SETUP_GUIDE.md")

SETTINGS_FILE = os.path.join(BASE_DIR, "astakos_settings.json")
SETTINGS_EXAMPLE = os.path.join(BASE_DIR, "astakos_settings.json.example")
PROMPTS_DIR = os.path.join(BASE_DIR, "prompts")

class SetupPayload(BaseModel):
    """Validated data submitted by the local Setup Wizard."""

    basic: dict
    advanced: dict
    prompts: dict
    routines: str = ""

def get_file_content(filepath, fallback_filepath=None):
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    if fallback_filepath and os.path.exists(fallback_filepath):
        with open(fallback_filepath, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def write_file_content(filepath, content):
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

@app.get("/", response_class=HTMLResponse)
async def serve_setup_page():
    html_path = os.path.join(STATIC_DIR, "setup.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="Error: setup.html not found.")

@app.get("/api/raw_files")
async def get_raw_files():
    env_content = get_file_content(ENV_FILE)
    if not env_content:
        env_content = """# --- LLM Provider Selection ---
LLM_PROVIDER=openai

# --- API Keys ---
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=

# --- Core Settings (Google Cloud & Telegram) ---
PROJECT_ID=your-gcp-project-id
LOCATION=us-central1
TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=
"""
    
    prompts_data = {}
    if os.path.exists(PROMPTS_DIR):
        for fname in os.listdir(PROMPTS_DIR):
            if fname.endswith(".md"):
                fpath = os.path.join(PROMPTS_DIR, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    prompts_data[f"prompts/{fname}"] = f.read()
                    
    import json
    try:
        settings_raw = get_file_content(SETTINGS_FILE, SETTINGS_EXAMPLE)
        settings_json = json.loads(settings_raw) if settings_raw else {}
    except Exception:
        settings_json = {}
    
    return {
        "persona": get_file_content(PERSONA_FILE, PERSONA_EXAMPLE),
        "intents": get_file_content(INTENTS_FILE, INTENTS_EXAMPLE),
        "routines": get_file_content(ROUTINES_FILE, ROUTINES_EXAMPLE),
        "env": env_content,
        "settings": settings_json,
        "prompts": prompts_data,
        "setup_guide": get_file_content(SETUP_GUIDE_FILE)
    }

@app.post("/api/setup")
async def save_setup(payload: SetupPayload):
    """Persist validated setup data and import first-run routine declarations once."""
    adv = payload.advanced
    basic = payload.basic
    prompts = payload.prompts
    routines_text = payload.routines.strip()

    if routines_text:
        from memory.routine_importer import RoutineImportError, validate_routine_import_text

        try:
            validate_routine_import_text(routines_text)
        except RoutineImportError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
    
    # Process ENV
    new_env = basic.get("env", "").strip()
    if basic.get("llm_provider") or basic.get("telegram_token"):
        env_lines = new_env.split('\n') if new_env else []
        env_map = {}
        for line in env_lines:
            if '=' in line and not line.strip().startswith('#'):
                k, v = line.split('=', 1)
                env_map[k.strip()] = v.strip()
        
        if basic.get("llm_provider"):
            env_map["LLM_PROVIDER"] = basic["llm_provider"]
            provider = basic["llm_provider"]
            if provider == "openai":
                env_map["OPENAI_API_KEY"] = basic.get("api_key", "")
            elif provider == "anthropic":
                env_map["ANTHROPIC_API_KEY"] = basic.get("api_key", "")
            elif provider == "gemini":
                env_map["GEMINI_API_KEY"] = basic.get("api_key", "")
            elif provider == "vertex":
                env_map["GOOGLE_APPLICATION_CREDENTIALS"] = basic.get("api_key", "")
                
        if basic.get("telegram_token"):
            env_map["TELEGRAM_TOKEN"] = basic["telegram_token"]
        if basic.get("telegram_chat_id"):
            env_map["TELEGRAM_CHAT_ID"] = basic["telegram_chat_id"]
            
        output_env = ""
        for k, v in env_map.items():
            output_env += f"{k}={v}\n"
        new_env = output_env

    write_file_content(ENV_FILE, new_env)
    
    # Write Settings
    import json
    if basic.get("settings"):
        write_file_content(SETTINGS_FILE, json.dumps(basic["settings"], indent=4))
    
    # Write other basics
    if basic.get("persona"):
        write_file_content(PERSONA_FILE, basic["persona"])
    if basic.get("intents"):
        write_file_content(INTENTS_FILE, basic["intents"])

    routine_import: dict[str, int | str] | None = None
    if routines_text:
        write_file_content(ROUTINES_FILE, f"{routines_text}\n")
        try:
            from memory.routine_importer import RoutineImportError, import_routines_file

            routine_import = import_routines_file(Path(ROUTINES_FILE))
        except RoutineImportError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        
    # Write prompts
    for p_path, content in prompts.items():
        if p_path.startswith("prompts/") and p_path.endswith(".md"):
            fname = os.path.basename(p_path)
            if fname in ("", ".", "..") or fname != p_path.removeprefix("prompts/"):
                continue
            full_path = os.path.join(PROMPTS_DIR, fname)
            write_file_content(full_path, content)

    def shutdown():
        time.sleep(2)
        os._exit(0)
    
    threading.Thread(target=shutdown).start()

    return {"status": "success", "routine_import": routine_import}

def run_wizard():
    host = os.getenv("ASTAKOS_SETUP_HOST", "127.0.0.1")
    port = int(os.getenv("ASTAKOS_SETUP_PORT", "8000"))
    print(f"Setup Wizard: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="error")

if __name__ == "__main__":
    run_wizard()
