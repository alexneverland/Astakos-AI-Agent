import os
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

_SENSITIVE_ENV_KEYS = frozenset({
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "TELEGRAM_TOKEN",
    "TELEGRAM_CHAT_ID",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "SPOTIFY_CLIENT_SECRET",
    "SPOTIFY_CLIENT_ID",
    "SPOTIPY_CLIENT_SECRET",
    "SPOTIPY_CLIENT_ID",
    "GITHUB_TOKEN",
    "EMAIL_PASSWORD",
    "VACUUM_TOKEN",
})

def sanitize_env_text(raw_env: str) -> str:
    """Masks secret values in .env so raw keys/tokens are never exposed over the API/UI."""
    if not raw_env:
        return ""
    lines = []
    for line in raw_env.splitlines():
        trimmed = line.strip()
        if trimmed and not trimmed.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            key_clean = key.strip()
            val_clean = val.strip()
            if (
                key_clean in _SENSITIVE_ENV_KEYS
                or key_clean.endswith("_KEY")
                or key_clean.endswith("_SECRET")
                or key_clean.endswith("_TOKEN")
                or key_clean.endswith("_PASSWORD")
            ):
                if val_clean:
                    lines.append(f"{key_clean}=********")
                else:
                    lines.append(f"{key_clean}=")
                continue
        lines.append(line)
    return "\n".join(lines)

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
    try:
        html_path = os.path.join(STATIC_DIR, "setup.html")
        if os.path.exists(html_path):
            with open(html_path, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
        return HTMLResponse(content="Error: setup.html not found.", status_code=404)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to load setup page.") from None

@app.get("/api/diagnostics")
async def get_diagnostics():
    """Returns non-sensitive runtime health and provider readiness."""
    try:
        from core.diagnostics import get_system_diagnostics_summary
        return get_system_diagnostics_summary()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to retrieve system diagnostics.") from None

@app.post("/api/workspace/connect")
async def connect_workspace(request: Request):
    """Explicit user-triggered Google Workspace OAuth authorization."""
    from core.workspace_oauth import (
        WorkspaceAuthError,
        authorize_workspace_oauth,
        get_workspace_oauth_flow,
    )
    try:
        if os.getenv("ASTAKOS_CONTAINER") == "1":
            start_res = await start_workspace_oauth(request)
            return {"status": "redirect", "auth_url": start_res["auth_url"]}

        authorize_workspace_oauth()
        return {"status": "success", "message": "Google Workspace connected successfully."}
    except WorkspaceAuthError:
        raise HTTPException(
            status_code=400,
            detail="Google Workspace authorization failed. Please check client_secrets.json and try again.",
        ) from None
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Google Workspace authorization encountered an internal error.",
        ) from None


@app.get("/api/workspace/oauth/start")
async def start_workspace_oauth(request: Request):
    """Starts browser-based OAuth consent flow routed through setup wizard port with CSRF state protection."""
    from core.workspace_oauth import (
        WorkspaceAuthError,
        create_workspace_oauth_authorization_url,
    )
    try:
        base_url = str(request.base_url).rstrip('/')
        auth_url = create_workspace_oauth_authorization_url(
            f"{base_url}/api/workspace/oauth/callback",
        )
        return {"auth_url": auth_url}
    except WorkspaceAuthError:
        raise HTTPException(
            status_code=400,
            detail="Google Workspace OAuth client secrets file not found. Please check credentials/client_secrets.json.",
        ) from None
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to initiate Google Workspace OAuth flow.") from None


@app.get("/api/workspace/oauth/callback", response_class=HTMLResponse)
async def workspace_oauth_callback(request: Request, code: str = "", state: str = ""):
    """Handles OAuth redirect callback, verifies CSRF state, and persists token.json."""
    from core.workspace_oauth import (
        WorkspaceOAuthStateError,
        complete_workspace_oauth_authorization,
    )
    try:
        base_url = str(request.base_url).rstrip('/')
        complete_workspace_oauth_authorization(
            f"{base_url}/api/workspace/oauth/callback",
            code,
            state,
        )
        return HTMLResponse(
            """<!DOCTYPE html>
<html>
<head><title>Authorization Successful</title></head>
<body style="font-family:system-ui,-apple-system,sans-serif;text-align:center;padding:50px 20px;background:#181825;color:#cdd6f4;">
  <div style="max-width:450px;margin:0 auto;background:#1e1e2e;padding:30px;border-radius:12px;border:1px solid #313244;">
    <h2 style="color:#a6e3a1;margin-top:0;">✅ Google Workspace Connected!</h2>
    <p style="color:#bac2de;font-size:14px;line-height:1.5;">Your authorization token has been saved successfully.</p>
    <p style="color:#6c7086;font-size:12px;">This window will close automatically...</p>
  </div>
  <script>
    if (window.opener) {
      try { window.opener.postMessage("oauth_complete", "*"); } catch(e) {}
    }
    setTimeout(() => window.close(), 1500);
  </script>
</body>
</html>"""
        )
    except WorkspaceOAuthStateError:
        return HTMLResponse(
            "<h3>Invalid or expired OAuth state. Please restart authorization from the Setup Wizard.</h3>",
            status_code=400,
        )
    except Exception:
        return HTMLResponse("<h3>Authorization failed. Please verify credentials/client_secrets.json.</h3>", status_code=400)



@app.get("/api/raw_files")
async def get_raw_files():
    try:
        env_content = get_file_content(ENV_FILE)
        if not env_content:
            env_content = """# --- LLM Provider Selection ---
LLM_PROVIDER=openai
EMBEDDINGS_PROVIDER=auto

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
            "env": sanitize_env_text(env_content),
            "settings": settings_json,
            "prompts": prompts_data,
            "setup_guide": get_file_content(SETUP_GUIDE_FILE)
        }
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to load configuration files.") from None

@app.post("/api/setup")
async def save_setup(payload: SetupPayload):
    """Persist validated setup data and import first-run routine declarations once."""
    try:
        adv = payload.advanced
        basic = payload.basic
        prompts = payload.prompts
        routines_text = payload.routines.strip()
        validated_routines: list[dict[str, str]] | None = None

        if routines_text:
            from memory.routine_importer import RoutineImportError, validate_routine_import_text

            try:
                validated_routines = validate_routine_import_text(routines_text)
            except RoutineImportError:
                raise HTTPException(
                    status_code=422,
                    detail="Routine validation failed. Please check routine definitions.",
                ) from None

        # Process ENV
        new_env = basic.get("env", "").strip()
        existing_env_raw = get_file_content(ENV_FILE)
        existing_env_map: dict[str, str] = {}
        if existing_env_raw:
            for line in existing_env_raw.splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    existing_env_map[k.strip()] = v.strip()

        env_map: dict[str, str] = {}
        if basic.get("llm_provider") or basic.get("embeddings_provider") or basic.get("telegram_token") or new_env:
            env_lines = new_env.split('\n') if new_env else []
            for line in env_lines:
                if '=' in line and not line.strip().startswith('#'):
                    k, v = line.split('=', 1)
                    env_map[k.strip()] = v.strip()

            # Merge unmentioned existing env keys
            for k, v in existing_env_map.items():
                if k not in env_map:
                    env_map[k] = v

            def _set_secret(key: str, new_val: str | None) -> None:
                """
                Sets a configuration secret in the environment map while preserving existing masked values.

                If `new_val` is provided and is not the mask placeholder '********', updates `env_map[key]`.
                If `new_val` is empty or '********', retains the previously stored value from `existing_env_map`.
                """
                if new_val and new_val != "********":
                    env_map[key] = new_val
                elif key not in env_map and key in existing_env_map:
                    env_map[key] = existing_env_map[key]
                elif env_map.get(key) == "********":
                    env_map[key] = existing_env_map.get(key, "")

            if basic.get("llm_provider"):
                env_map["LLM_PROVIDER"] = basic["llm_provider"]
                provider = basic["llm_provider"]
                api_key = basic.get("api_key")
                if provider == "openai":
                    _set_secret("OPENAI_API_KEY", api_key)
                elif provider == "anthropic":
                    _set_secret("ANTHROPIC_API_KEY", api_key)
                elif provider == "gemini":
                    _set_secret("GEMINI_API_KEY", api_key)
                elif provider == "vertex":
                    _set_secret("GOOGLE_APPLICATION_CREDENTIALS", api_key)

            if basic.get("embeddings_provider"):
                env_map["EMBEDDINGS_PROVIDER"] = basic["embeddings_provider"]
                emb_provider = basic["embeddings_provider"]
                emb_api_key = basic.get("embeddings_api_key")
                if emb_api_key:
                    if emb_provider == "openai":
                        _set_secret("OPENAI_API_KEY", emb_api_key)
                    elif emb_provider == "gemini":
                        _set_secret("GEMINI_API_KEY", emb_api_key)
                    elif emb_provider == "vertex":
                        _set_secret("GOOGLE_APPLICATION_CREDENTIALS", emb_api_key)

            if basic.get("telegram_token"):
                _set_secret("TELEGRAM_TOKEN", basic["telegram_token"])
            if basic.get("telegram_chat_id"):
                _set_secret("TELEGRAM_CHAT_ID", basic["telegram_chat_id"])

            # If Vertex is selected (chat or embeddings), resolve actual project ID if placeholder or empty
            if env_map.get("LLM_PROVIDER") == "vertex" or env_map.get("EMBEDDINGS_PROVIDER") == "vertex":
                current_proj = env_map.get("PROJECT_ID", "").strip()
                if not current_proj or current_proj.lower() == "your-gcp-project-id":
                    from core.ai_provider import resolve_vertex_project_id
                    cred_target = env_map.get("GOOGLE_APPLICATION_CREDENTIALS")
                    resolved_proj = resolve_vertex_project_id(cred_file=cred_target)
                    if resolved_proj and resolved_proj.lower() != "your-gcp-project-id":
                        env_map["PROJECT_ID"] = resolved_proj

            # Resolve any remaining masked keys
            for k, v in list(env_map.items()):
                if v == "********":
                    env_map[k] = existing_env_map.get(k, "")

            output_env = ""
            for k, v in env_map.items():
                output_env += f"{k}={v}\n"
            new_env = output_env
        else:
            env_map = dict(existing_env_map)

        write_file_content(ENV_FILE, new_env)

        # Write Settings (preserve unedited existing settings while removing cleared child names)
        import json
        if basic.get("settings") is not None:
            existing_settings_raw = get_file_content(SETTINGS_FILE)
            try:
                existing_settings = json.loads(existing_settings_raw) if existing_settings_raw else {}
            except Exception:
                existing_settings = {}
            merged_settings = {**existing_settings, **basic["settings"]}
            if "kid1_name" not in basic["settings"]:
                merged_settings.pop("kid1_name", None)
            if "kid2_name" not in basic["settings"]:
                merged_settings.pop("kid2_name", None)
            write_file_content(SETTINGS_FILE, json.dumps(merged_settings, indent=4))


        # Write other basics
        if basic.get("persona"):
            write_file_content(PERSONA_FILE, basic["persona"])
        if basic.get("intents"):
            write_file_content(INTENTS_FILE, basic["intents"])

        routine_import: dict[str, int | str] | None = None
        if routines_text and validated_routines is not None:
            write_file_content(ROUTINES_FILE, f"{routines_text}\n")
            try:
                from memory.routine_importer import RoutineImportError, import_validated_routines

                routine_import = import_validated_routines(validated_routines)
            except RoutineImportError:
                raise HTTPException(
                    status_code=422,
                    detail="Routine validation failed. Please check routine definitions.",
                ) from None

        # Write prompts
        for p_path, content in prompts.items():
            if p_path.startswith("prompts/") and p_path.endswith(".md"):
                fname = os.path.basename(p_path)
                if fname in ("", ".", "..") or fname != p_path.removeprefix("prompts/"):
                    continue
                full_path = os.path.join(PROMPTS_DIR, fname)
                write_file_content(full_path, content)

        from core.diagnostics import get_system_diagnostics_summary
        diagnostics = get_system_diagnostics_summary(
            chat_provider=basic.get("llm_provider"),
            embeddings_provider=basic.get("embeddings_provider"),
            env_snapshot=env_map,
        )

        def shutdown():
            time.sleep(2)
            os._exit(0)

        threading.Thread(target=shutdown).start()

        return {
            "status": "success",
            "routine_import": routine_import,
            "diagnostics": diagnostics,
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to persist setup configuration.") from None


def run_wizard():

    host = os.getenv("ASTAKOS_SETUP_HOST", "127.0.0.1")
    port = int(os.getenv("ASTAKOS_SETUP_PORT", "8000"))
    print(f"Setup Wizard: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="error")

if __name__ == "__main__":
    run_wizard()
