import os
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import threading
import time

app = FastAPI(title="Astakos Setup Wizard")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "api", "static")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

ENV_FILE = os.path.join(BASE_DIR, ".env")
PERSONA_FILE = os.path.join(BASE_DIR, "persona.md")
PERSONA_EXAMPLE = os.path.join(BASE_DIR, "persona.md.example")
INTENTS_FILE = os.path.join(BASE_DIR, "astakos_custom_intents.json")
INTENTS_EXAMPLE = os.path.join(BASE_DIR, "astakos_custom_intents.json.example")
SETUP_GUIDE_FILE = os.path.join(BASE_DIR, "SETUP_GUIDE.md")

class SetupPayload(BaseModel):
    basic: dict
    advanced: dict

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
    # If .env does not exist, extract the template from SETUP_GUIDE.md or return basic template
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
    
    return {
        "persona": get_file_content(PERSONA_FILE, PERSONA_EXAMPLE),
        "intents": get_file_content(INTENTS_FILE, INTENTS_EXAMPLE),
        "env": env_content
    }

@app.post("/api/setup")
async def save_setup(payload: SetupPayload):
    adv = payload.advanced
    basic = payload.basic
    
    # Process ENV
    new_env = adv.get("env", "").strip()
    if basic.get("llm_provider") or basic.get("telegram_token"):
        # We need to parse new_env and inject basic overrides if they were filled out
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
                
        if basic.get("telegram_token"):
            env_map["TELEGRAM_TOKEN"] = basic["telegram_token"]
        if basic.get("telegram_chat_id"):
            env_map["TELEGRAM_CHAT_ID"] = basic["telegram_chat_id"]
            
        # Reconstruct env content
        output_env = ""
        for k, v in env_map.items():
            output_env += f"{k}={v}\n"
        # If user didn't have an env, just write the mapped version.
        new_env = output_env

    write_file_content(ENV_FILE, new_env)
    
    # Write others
    if adv.get("persona"):
        write_file_content(PERSONA_FILE, adv["persona"])
    if adv.get("intents"):
        write_file_content(INTENTS_FILE, adv["intents"])

    # Trigger shutdown so boot.py can continue
    def shutdown():
        time.sleep(2)
        os._exit(0)
    
    threading.Thread(target=shutdown).start()

    return {"status": "success"}

def run_wizard():
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")

if __name__ == "__main__":
    run_wizard()
