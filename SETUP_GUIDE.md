# Astakos AI - Beginner's Setup Guide

Welcome to the Astakos AI setup guide. Follow these steps to run your assistant locally with your own configuration and data.

This guide focuses on **Vertex AI**, but the Web Setup Wizard also supports **Gemini API**, **OpenAI**, and **Anthropic**.

---

## Step 1: Prerequisites

Install these first:

1. Python 3.11 or newer.
2. Docker Desktop if you want the Docker path.
3. Google Cloud credentials JSON if you plan to use `LLM_PROVIDER=vertex`.

---

## Step 2: Clone and Install

```bash
git clone https://github.com/alexneverland/Astakos-AI-Agent.git
cd Astakos-AI-Agent
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Astakos also ships with a committed `.env.example` template:

```bash
copy .env.example .env
```

---

## Step 3: Prepare Provider Credentials

### Vertex AI

If you use Vertex, place your Google credentials JSON locally, for example:

```text
credentials/credentials.json
```

Then set these values either in the Web Setup Wizard or in `.env`:

```env
LLM_PROVIDER=vertex
GOOGLE_APPLICATION_CREDENTIALS=credentials/credentials.json
PROJECT_ID=your-gcp-project-id
LOCATION=us-central1
```

### Other Providers

- Gemini API: set `LLM_PROVIDER=gemini` and `GEMINI_API_KEY`
- OpenAI: set `LLM_PROVIDER=openai` and `OPENAI_API_KEY`
- Anthropic: set `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`

---

## Step 4: Run the Setup Wizard

If you want the guided path:

- On Windows, double click `start_astakos.bat`
- Or run:

```bash
python boot.py
```

If Astakos is unconfigured, it will launch the Web Setup Wizard automatically.

To reopen the wizard later:

```bash
python boot.py --setup
```

The wizard writes local config files such as `.env`, `astakos_settings.json`, and your customized prompts on your machine.

---

## Step 5: Start Astakos

### Local CLI

```bash
python boot.py
```

### Docker / Headless

```bash
docker compose up --build -d
```

This path runs `boot.py --server`, which starts the API server and Telegram bot together.

---

## Step 6: Start Chatting

Once configured:

1. Open Telegram.
2. Find your bot.
3. Send a message.

If the API server is running, the runtime dashboard is available at:

```text
http://localhost:8000/debug/runtime
```
