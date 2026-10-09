# Astakos AI — Beginner Setup Guide

Run your own personal AI assistant on your computer without manually building a Python environment.

The recommended installation uses **Docker Desktop**. Docker installs the Python dependencies, browser components, and runtime services inside an isolated container while your memories, settings, databases, and files remain on your computer: in the project folder for a source build or in a named Docker volume for the release image.

This guide covers **v2.8.0** (2026-10-09), including the guided Wizard and native
Office provisioning. Optional services still require the explicit setup below.
See [release verification and upgrade notes](docs/release-readiness.md).

Use this guide with the v2.8.0 source/tag or verified release artifacts. Until
its publishing workflow and GitHub release complete, `latest` may still deliver
v2.7.0; confirm the [v2.8.0 release](https://github.com/alexneverland/Astakos-AI-Agent/releases/tag/v2.8.0)
is available before using the release downloads.

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

You only need **one chat provider** to start. Gemini API, OpenAI, and Vertex AI can also provide semantic-memory embeddings and voice automatically. Anthropic can run chat by itself, but semantic memory and voice need a compatible second provider as described below.

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

Choose a **Chat Provider** and enter its credential. Then choose an **Embeddings Provider** for long-term semantic memory and a **Voice Provider** for transcription and spoken replies:

- For Gemini API, OpenAI, or Vertex AI, leave Embeddings Provider on **Auto** for the simplest setup.
- For Anthropic, choose Vertex AI, Gemini API, OpenAI, or Local Multilingual E5 explicitly. Anthropic does not offer native embeddings.
- Leave Voice Provider on **Auto** when chat uses Vertex AI, Gemini API, or OpenAI. With Anthropic chat, explicitly choose one of those three voice providers and provide its credential.
- Choose **Telegram** or **Element / Matrix** as Astakos's active external app. The Web UI remains available either way. The Setup Wizard retains the inactive app's settings so you can switch later without re-entering them.

The Basic Settings steps cover:

1. **AI Brain & APIs:** chat, embeddings and voice providers/credentials; Vertex project override and region.
2. **External messaging:** Telegram or Matrix credentials and trusted owner/device/room settings.
3. **Personalization:** owner, companion, family names, language, city and voice wake name.
4. **Google Workspace:** explicit OAuth connection and Drive/Gmail/Calendar/Tasks/Fit readiness.
5. **Location, Files & Backups:** optional home/work coordinate pairs and radii, local project alias, native Office tool status/install command, and the private Drive data-backup folder ID.
6. **Optional Integrations:** GitHub token, vacuum local IP/token, LinkedIn token, Google Places key and Spotify client credentials/redirect URI. Unused integrations can remain blank; masked existing tokens are preserved.
7. **Core Config Files:** persona, local custom intents and advanced environment settings.

The **Routines** tab validates and imports declared routines only into an empty
routine catalogue. **Advanced Prompts** edits the existing prompt files. Location
pairs must both be filled or both blank; latitude/longitude ranges and positive
radii are validated before writes. Leave locations blank when unknown. The backup
field accepts a folder ID, not a URL; saving it does not create a scheduled task.
Office status verifies the native executable's pinned size and SHA-256 for the
current platform. It does not run a live functionality test. Clearing a supplied
optional non-secret field removes its saved value; omitted fields and masked
secrets retain their saved values.
Backup schedules, Matrix server deployment, Element recovery keys and local E5
model installation remain explicit operator steps; use the linked instructions.

Home/work coordinates define known places; they do not turn on phone tracking.
GPS context arrives only when the owner shares location through the active
Telegram or Matrix app. Allow location access on the phone when using that
feature; client support for location/live updates varies. A static point is not
continuous tracking, and GPS never proves partner/child presence.

For Google Places, enable the Places API for the supplied key and apply suitable
key restrictions. For Spotify, create a developer app, enter its client ID/secret,
and register the exact redirect URI you enter in the Wizard. A manual local
installation can use `http://127.0.0.1:8888/callback`; external callbacks require
HTTPS, and `localhost` is not accepted by Spotify. See the
[official redirect requirements](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri).
Complete Spotify consent on first use. Docker's default Compose publishes only
port 8000: Spotify callback access/port mapping and interactive OAuth must be
configured separately; saved credentials do not prove Spotify readiness.

### External messaging: Telegram or Element / Matrix

Astakos uses one external messaging transport at a time. This avoids duplicate
approvals, reminders, and routine messages. Switching the active app is done in
the Setup Wizard. Web, Telegram, and Matrix use shared conversation history and
context. Web messages are mirrored to the currently selected external app;
switching that app does not erase the shared history. Original attachments and
generated files are not copied between apps.

#### Telegram

Telegram is optional. You can save and use the Web UI first, then add a
BotFather token and your Telegram chat ID later. Select **Telegram** in the
Setup Wizard when you want it to receive Astakos messages again.

#### Element / Matrix

Matrix gives you a private mobile app through Element while keeping the server
under your control. Before selecting **Element / Matrix** in the Setup Wizard:

1. Install **Element** or **Element X** on each phone and sign in to your
   private homeserver. Each person needs their own Matrix account.
2. Create a dedicated Matrix account for Astakos, separate from every family
   member's account.
3. Create one private encrypted room for Astakos, invite only your owner
   account and the dedicated Astakos account, then copy the exact room ID
   (`!room:server`).
4. Obtain an access token for the dedicated Astakos account through your
   homeserver's secure administration procedure. Treat it like a password:
   do not share it or commit it to Git.
5. In Element, open **Settings → Security & Privacy → Sessions**, select your
   current trusted phone/session, and copy its exact **Device ID**. Repeat for
   any other owner device that Astakos may send encrypted replies to.
6. In the Setup Wizard, choose **Element / Matrix** and enter the homeserver
   URL, Astakos user ID, access token, owner user ID, trusted owner Device IDs
   (comma-separated), encrypted room ID, and a persistent crypto-store path.
   The default `matrix_store` is suitable when it is kept on persistent
   storage. A new Element session remains blocked until you explicitly add its
   Device ID and restart Astakos.

For a normal family conversation, create a **different encrypted room** for
you and your family and do **not** invite the Astakos account. Astakos
can only see rooms to which its own account is invited; the family room stays
separate from the assistant.

Matrix approvals use an exact **Reply** to Astakos's approval message. Reactions
are not approvals. Shared context and location updates do not authorize sending
messages to another person. The release compose file starts Astakos, not a
Matrix homeserver; operate and back up that server separately. See the
[Matrix recovery runbook](docs/matrix-backup-recovery.md).

In source versions after v2.8.0, a new local reminder grounded in your own current request follows the normal
WARNING policy, even after an unrelated memory or web lookup. If its task or
schedule depends on external content, is ambiguous, or cannot be validated,
approval remains required. Fresh external tool results retain their safety gate.
After an approved reminder runs, Matrix shows its actual result and task and
records the outcome in the originating history; a tool error remains visible.

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

### Voice and Live Voice

Voice input and spoken replies are independent from semantic-memory embeddings.

| Choice | Credentials and behavior |
|---|---|
| **Auto** | Reuses Vertex AI, Gemini API, or OpenAI when that provider powers chat. |
| **Vertex AI** | Uses dedicated Google transcription and Google Cloud Text-to-Speech with the mounted service-account JSON. Enable the Cloud Text-to-Speech API for the project. |
| **Gemini API** | Uses the Gemini API key for transcription and speech synthesis. |
| **OpenAI** | Uses the OpenAI API key for transcription and speech synthesis. |

The Setup Wizard also lets you choose the **Live Voice wake name**. In the Web
UI, select **LIVE** and say that name once while Astakos is in standby. After it
wakes, the conversation continues without requiring the name before every
sentence. Microphone capture pauses while Astakos speaks and resumes afterward.

If a provider is unauthorized, over quota, or missing a required API, Web Live
Voice shows the provider error and keeps the text reply available. For Vertex
speech failures, first verify the mounted service-account path, project,
location, permissions, and that Cloud Text-to-Speech is enabled.

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

Astakos creates `credentials/token.json` after successful consent. Keep both files private. If a Workspace action later reports that authorization has expired, been revoked, or lacks a permission, use the same **Connect / Reconnect Google Workspace** button to authorize again. Do not replace a Vertex service-account JSON with the Workspace OAuth files: they serve different purposes.

The wizard writes local configuration such as `.env`, `astakos_settings.json`, and customized prompts into your Astakos folder. These runtime files are excluded from Git.

`astakos_custom_intents.json` is also a local, Git-excluded overlay for private aliases and vocabulary. Copy its `.example` file when you want to add family aliases or personal trigger words; do not add those values to the shared intent files.

## Step 5 — Start Chatting

Use the Web UI at:

```text
http://localhost:8000
```

When Telegram is selected and configured, open your bot and send it a message.
When Matrix is selected, use the configured encrypted owner/Astakos room in Element.
See [routines and context](docs/routines-and-context.md) for Active/Suppressed,
expiry, context questions and the difference between acknowledgement and completion.

The runtime dashboard is available at:

```text
http://localhost:8000/debug/runtime
```

---

## Everyday Docker Commands

The commands below use source-build `docker-compose.yml`. For the downloaded
release deployment, add `-f docker-compose.release.yml` after `docker compose`.
Release updates pull the published image; they do not build source `main`.
The README documents [release commands](README.md#useful-release-commands).

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

The source compose deployment maps the project directory into the container.
The release compose deployment instead uses `astakos_data` and
`astakos_workspace` named volumes plus a host credentials mount.

> `docker compose down -v` removes named volumes and can destroy release runtime
> data and OAuth tokens. Normal `down` preserves them. Backups are separate from
> volume persistence; see [data backup](docs/daily-data-backup.md).

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

### Selected external app

```bash
python run_external.py
```

This selects the configured Telegram or Matrix supervisor. For a deliberately
selected standalone transport, use `python run_telegram.py` or `python run_matrix.py`.

### Web UI and API supervisor

```bash
python run_web.py
```

### API server and selected external app together

```bash
python boot.py --server
```

On Windows, `start_astakos.bat` launches the Web and selected external supervisors.
Those source supervisors restart their child process when watched Python sources
or supported prompt files change; do not manually restart after every code edit.
`boot.py --server` is the combined startup path, not the same source-watch loop.
Configuration/provider changes still require a controlled restart. These local
supervisors also coordinate supported backup pauses; direct `uvicorn --reload`
is not a substitute for the normal operator startup path.

---

# File Creation and Office Support

Astakos uses native generators directly for PDF, TXT and CSV. Word, Excel and
PowerPoint workflows prefer Office CLI; supported DOCX/XLSX generators are
fallbacks when it is unavailable or cannot cover the requested structure.
They are not PowerPoint generators and do not bypass approval checks.

Docker builds provision the checksum-verified native Office CLI v1.0.154.
For manual Python installs, run `python scripts/install_officecli.py` from the
project directory using your configured Python environment. The installer selects
Windows, Linux or macOS x64/ARM64, checks size and SHA-256, and replaces atomically.
Linux requires ICU; the Debian Trixie Docker images include `libicu76`. Linux
musl/Alpine is not covered. The canonical path is `vendor/officecli/officecli.exe`
on Windows and `vendor/officecli/officecli` elsewhere. Docker additionally keeps
`/opt/astakos-tools/officecli` available when source Compose mounts the checkout
over `/app`. The installer does not
configure MCP, install host packages or execute upstream installers. Missing or
unsupported tooling is visible in Wizard step 5. Generated files are discovered in `outputs/` and delivered through
the originating channel; Web mirroring does not duplicate them to another app.

---

# Where Your Data Lives

Astakos is local-first. Manual/source deployments keep runtime state in the project folder; release Docker keeps it in persistent volumes. This includes:

- SQLite conversation, profile, routine, state, and analytics databases
- `chroma_db/` semantic memory
- local configuration and prompt files
- logs, uploads, generated files, and media indexes

The configured AI provider and enabled integrations may receive prompts, uploaded media, or tool payloads required to perform their jobs. Local-first does not mean that external AI APIs magically stop being external.

Before a major upgrade, preserve the runtime data and credentials securely.
The [daily data-only backup](docs/daily-data-backup.md) excludes credentials,
`.env`, code and unindexed outputs. The [Matrix encrypted backup](docs/matrix-backup-recovery.md)
covers a different server/bot inventory; Element recovery keys remain separate.
Neither workflow is automatically installed for a new Docker user.

Normal startup prepares dated routine storage in the routine database transaction
for new and existing installations. Existing feedback, baselines and routines are
preserved; no manual reset or historical backfill is required. Release updates
preserve runtime JSON, registered context flags, Matrix crypto/media and backups
while refreshing application registries and code. See
[release readiness](docs/release-readiness.md) for verification scope.

---

# Troubleshooting

## Element says the server is offline

Check the phone's network/VPN and whether the configured homeserver URL is
reachable. A homeserver outage is separate from the Astakos Python transport;
restarting only Astakos cannot restore an unavailable Matrix server. If Element
can reach the server but Astakos does not reply, check the selected transport,
encrypted room, configured trusted Device IDs and transport logs. A newly signed-in
Element session needs its Device ID explicitly trusted and Astakos restarted.
Preserve the crypto store while diagnosing; deleting it is not a connectivity fix.

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
