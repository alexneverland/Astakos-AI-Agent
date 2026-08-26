# Astakos AI — Beginner Setup Guide

Run your own personal AI assistant on your computer without manually building a Python environment.

The recommended installation uses **Docker Desktop**. Docker installs the Python dependencies, browser components, and runtime services inside an isolated container while your memories, settings, databases, and files remain on your computer: in the project folder for a source build or in a named Docker volume for the release image.

> **What you need:** Docker Desktop, one supported AI provider, and about 10 minutes for the first setup.

---

## Choose Your Setup Path

| Path | Best for | What you install manually |
|---|---|---|
| **Docker — recommended** | Most users, Windows/macOS/Linux, clean installation | Docker Desktop only |
| **Docker release image** | Users who want automatic image updates | Docker Desktop only |
| **Manual Python setup** | Developers who want to modify or debug the code directly | Python 3.11+, virtual environment, dependencies |

Astakos supports these model providers:

- **Gemini API** — simplest Google setup; requires a Gemini API key.
- **OpenAI** — requires an OpenAI API key.
- **Anthropic** — requires an Anthropic API key.
- **Vertex AI** — intended for Google Cloud users; requires a project and credentials JSON.

You only need **one chat provider** to start. Gemini API, OpenAI, and Vertex AI can also provide semantic-memory embeddings automatically. Anthropic can run chat by itself, but semantic memory needs a second embeddings provider or the optional local model described below.

> Want automatic Docker image updates instead of building from source? Download `docker-compose.release.yml` from the [latest release](https://github.com/alexneverland/Astakos-AI-Agent/releases/latest), place it in an empty folder, and run `docker compose -f docker-compose.release.yml up -d`. The full release-image instructions are in the [README](README.md#recommended-docker-with-automatic-updates).

---

# Recommended: Docker Setup

## Step 1 — Install Docker Desktop

Download and install Docker Desktop for your operating system, then open it and wait until Docker reports that it is running.

On Windows, Docker Desktop may ask you to enable WSL 2. Follow its instructions and restart Windows if requested.

You do **not** need to install Python for the Docker path.

## Step 2 — Download Astakos

### Option A: Git

```bash
git clone https://github.com/alexneverland/Astakos-AI-Agent.git
cd Astakos-AI-Agent
```

### Option B: ZIP

1. Open the repository on GitHub.
2. Select **Code → Download ZIP**.
3. Extract the ZIP to a normal writable folder.
4. Open a terminal inside the extracted folder.

Avoid protected folders such as `Program Files` because Astakos stores its local state inside the project folder.

## Step 3 — Start Astakos

Run:

```bash
docker compose up --build -d
```

The first launch takes longer because Docker builds the image and installs the required components. Later launches reuse the existing image.

When the container is running, open:

```text
http://localhost:8000
```

Astakos will show the Web Setup Wizard when it has not been configured yet.

> **Note:** Docker setup does not require Telegram on first launch. Astakos can start in Web/API mode with only one supported AI provider configured. Telegram becomes available after you add `TELEGRAM_TOKEN`.

## Step 4 — Complete the Setup Wizard

Choose a **Chat Provider** and enter its credential. Then choose an **Embeddings Provider** for long-term semantic memory:

- For Gemini API, OpenAI, or Vertex AI, leave Embeddings Provider on **Auto** for the simplest setup.
- For Anthropic, choose Vertex AI, Gemini API, OpenAI, or Local Multilingual E5 explicitly. Anthropic does not offer native embeddings.
- Telegram is optional. You can save and use the Web UI first, then add a BotFather token and your Telegram chat ID later.

The wizard's diagnostics show whether chat, semantic memory, and optional Google Workspace integrations are ready. A missing embeddings provider does not stop basic chat and tools, but long-term semantic recall remains unavailable until it is configured.

### Optional: declare your weekly routines

The **Routines** tab contains the local `astakos_routines.json` template. Add
only routines you want from the first day, then save setup. Astakos validates
the complete JSON before writing it and imports it only into an empty routines
database; an existing routine database is never overwritten. The local file is
preserved by release Docker updates. See [the routine JSON reference](docs/routine-json-import.md)
for the exact schema.

### Gemini API

You need:

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-key
```

### OpenAI

You need:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your-key
```

### Anthropic

You need:

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-key
```

Also select a separate embeddings provider in the Setup Wizard. See **Semantic Memory / Embeddings** below.

### Semantic Memory / Embeddings

Embeddings power meaning-based recall of saved facts, conversations, documents, and photos. They are independent from the chat provider.

| Choice | Best for | What it needs |
|---|---|---|
| **Auto** | Gemini API, OpenAI, or Vertex AI chat | Uses that provider's native embeddings. |
| **Vertex AI** | Google Cloud users | The same valid Vertex credentials JSON. |
| **Gemini API** | Gemini API users | A Gemini API key. |
| **OpenAI** | OpenAI or Anthropic chat users | An OpenAI API key. |
| **Local Multilingual E5** | Advanced manual installations that require local embeddings | `sentence-transformers` plus a model downloaded locally. |

Astakos never silently chooses a different cloud provider and never downloads a local model by itself.

#### Local Multilingual E5 (advanced, manual Python setup)

Use this only when you intentionally want semantic embeddings to run on the computer. The normal Docker release image does not include this optional dependency or model; choose a cloud embeddings provider unless you maintain a custom Docker image.

For a manual Python installation, while the virtual environment is active:

```powershell
pip install sentence-transformers
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-small')"
```

Then select **Local Multilingual E5** in the Wizard and save. Astakos checks only whether the package and model already exist locally; it will not install or download them during startup.

#### Changing embeddings later

Changing the embeddings provider or model creates a separate semantic-memory collection so incompatible vectors are never mixed. Astakos keeps the old collection intact, but its old entries are not searched by the new backend automatically. Keep the current provider if immediate recall of existing semantic memories matters; the diagnostics page reports when historical memory belongs to another collection.

### Vertex AI

Vertex AI in Docker requires a real Google service-account JSON file that is mounted into the container.

1. In Google Cloud Console, create or choose a service account for Vertex AI.
2. Grant it the access your project needs for Vertex AI.
3. Create a **JSON** key for that service account and download it.
4. In the same folder as the Compose file you started, create a local folder named `credentials/`.
5. Copy the downloaded JSON file into that folder, for example:

```text
credentials/vertex-service-account.json
```

6. The source Docker Compose setup maps the project folder to `/app`, and `docker-compose.release.yml` mounts `./credentials` explicitly. In either setup, the credentials folder is available in the container as `/app/credentials`.

7. Then provide:

```env
LLM_PROVIDER=vertex
GOOGLE_APPLICATION_CREDENTIALS=/app/credentials/vertex-service-account.json
PROJECT_ID=your-gcp-project-id
LOCATION=global
# Optional: leave blank for the tested daily-model default.
ASTAKOS_GEMINI_FAST_MODEL=
```

If `GOOGLE_APPLICATION_CREDENTIALS` is empty, or points to a host-only path that does not exist inside the container, Astakos will return to the Setup Wizard instead of booting.

### Optional: Google Workspace integrations

Google Workspace is separate from both your chat provider and Vertex service-account credentials. It enables Gmail, Google Drive, Calendar, Tasks, Google Fit, and Daily Backup with **your personal Google account**.

1. In Google Cloud Console, enable the Google APIs you intend to use (Gmail, Drive, Calendar, Tasks, and Fitness for Google Fit).
2. Create a Google OAuth 2.0 client that allows the local callback `http://localhost:8000/api/workspace/oauth/callback`, then download its client-secrets JSON.
3. Save it as:

```text
credentials/client_secrets.json
```

4. Open the Setup Wizard and select **Connect / Reconnect Google Workspace**. Complete Google's consent screen in the popup.

Astakos creates `credentials/token.json` after successful consent. Keep both files private. If the token is revoked, the diagnostics page will say **Reconnect**; use the same button to authorize again. Do not replace a Vertex service-account JSON with the Workspace OAuth files: they serve different purposes.

The wizard writes local configuration such as `.env`, `astakos_settings.json`, and customized prompts into your Astakos folder. These runtime files are excluded from Git.

`astakos_custom_intents.json` is also a local, Git-excluded overlay for private aliases and vocabulary. Copy its `.example` file when you want to add family aliases or personal trigger words; do not add those values to the shared intent files.

## Step 5 — Start Chatting

Use the Web UI at:

```text
http://localhost:8000
```

When Telegram is configured, open your bot and send it a message.

The runtime dashboard is available at:

```text
http://localhost:8000/debug/runtime
```

---

## Everyday Docker Commands

### View status

```bash
docker compose ps
```

### View live logs

```bash
docker compose logs -f
```

Press `Ctrl+C` to stop viewing logs. This does not stop Astakos.

### Stop Astakos

```bash
docker compose down
```

### Start it again

```bash
docker compose up -d
```

### Rebuild after an update

```bash
git pull
docker compose up --build -d
```

Your local databases and configuration remain in the project folder because Docker maps that folder into the container.

> Do not use `docker compose down -v` unless you understand what volumes are being removed. Astakos currently persists its main runtime state through the mapped project directory, but deleting data blindly is never a clever backup strategy.

---

# Manual Python Setup

Use this path when you want direct access to the Python environment or plan to develop Astakos.

## Step 1 — Requirements

Install:

- Python 3.11 or newer
- Git
- A supported AI provider credential

## Step 2 — Clone and Create the Environment

### Windows

```powershell
git clone https://github.com/alexneverland/Astakos-AI-Agent.git
cd Astakos-AI-Agent
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

### Linux / macOS

```bash
git clone https://github.com/alexneverland/Astakos-AI-Agent.git
cd Astakos-AI-Agent
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Step 3 — Launch the Wizard

```bash
python boot.py
```

When Astakos is unconfigured, `boot.py` opens the Web Setup Wizard automatically.

To reopen it later:

```bash
python boot.py --setup
```

On Windows, you can also double-click:

```text
start_astakos.bat
```

## Step 4 — Run Individual Components

### Telegram bot

```bash
python run_telegram.py
```

### Web UI and API

```bash
uvicorn api.server:server --reload
```

### API server and Telegram together

```bash
python boot.py --server
```

---

# Where Your Data Lives

Astakos is local-first. Its runtime state is stored in the project folder, including:

- SQLite conversation, profile, routine, state, and analytics databases
- `chroma_db/` semantic memory
- local configuration and prompt files
- logs, uploads, generated files, and media indexes

The configured AI provider and enabled integrations may receive prompts, uploaded media, or tool payloads required to perform their jobs. Local-first does not mean that external AI APIs magically stop being external.

Back up the complete Astakos folder before major upgrades if the stored memory matters to you.

---

# Troubleshooting

## The browser cannot open `localhost:8000`

Check the container:

```bash
docker compose ps
```

Then inspect the logs:

```bash
docker compose logs --tail=200
```

## Port 8000 is already in use

Stop the other application using port 8000, or change the left side of the port mapping in `docker-compose.yml`, for example:

```yaml
ports:
  - "8080:8000"
```

Then open:

```text
http://localhost:8080
```

## Docker command is not recognized

Docker Desktop is either not installed, not running, or your terminal was opened before installation completed. Start Docker Desktop and reopen the terminal.

## Provider authentication fails

Confirm that:

- the selected provider matches the credential you entered;
- the API key has no extra spaces or quotation marks;
- Vertex AI credentials point to a file that exists inside the project folder;
- the provider account has access and billing configured where required.

## I changed the configuration and want the wizard again

For a manual installation:

```bash
python boot.py --setup
```

For Docker, open the Web UI and use the available setup/configuration flow. You can also restart the container after editing `.env`:

```bash
docker compose restart
```

---

## Security Notes

- Never commit `.env`, API keys, OAuth tokens, credentials JSON files, databases, or private uploads.
- Keep Astakos bound to localhost unless you deliberately add authentication, TLS, and network restrictions.
- Review CRITICAL approval requests before accepting them.
- Treat public Google Drive links as public links.

---

## Need Help?

Open a GitHub issue and include:

- your operating system;
- whether you used Docker or manual Python;
- the command you ran;
- the relevant error message or a short log excerpt;
- no API keys, tokens, passwords, or credential files.
