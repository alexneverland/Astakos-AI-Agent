# Astakos AI Agent v2.0.0

**Released: 2026-07-15**

## Astakos is now portable, Docker-first, and ready for other people to run

Version 2.0.0 marks the transition from a powerful personal installation into a self-hosted AI agent that other users can realistically download, configure, and run on their own computer.

The core intelligence remains the same: shared long-term memory, proactive routines, conversational follow-ups, multi-agent orchestration, planning, approvals, tools, analytics, and local state. The major change is that the project is no longer tied to one machine or one person's configuration.

## Highlights

- **Docker-first installation** with one main command:

  ```bash
  docker compose up --build -d
  ```

- **Web Setup Wizard** available at `http://localhost:8000`.
- **No manual Python environment, dependency hunting, or Playwright setup** for the recommended Docker path.
- **Download ZIP support** for users who do not use Git.
- **Provider-agnostic setup** supporting Vertex AI, Gemini API, OpenAI, and Anthropic.
- **Portable configuration** with committed `.env.example` and locally generated private settings.
- **Local persistence** for SQLite databases, ChromaDB, logs, settings, uploads, and generated files through Docker volume mapping.
- **Docker/headless startup** runs the Web API and Telegram bot together.
- **Beginner-focused documentation** with start, stop, update, logs, backup, and troubleshooting instructions.

## Added

- Docker-first quick-start flow.
- Guided setup for supported model providers.
- Portable boot and server startup paths.
- Hacker News daily technology briefing with scheduler support and deterministic fallback formatting.
- Additional portability and setup tests.
- Clear public-facing documentation explaining local-first storage and external API usage.

## Changed

- Refactored runtime configuration so the project no longer depends on machine-specific paths or personal settings.
- Removed remaining personal hardcodes, scratch scripts, runtime artifacts, and local-only files from the public repository.
- Reworked `README.md` from a developer-heavy feature inventory into a Docker-first product landing page.
- Reworked `SETUP_GUIDE.md` so Docker is the recommended path and manual Python installation is the advanced alternative.
- Aligned `boot.py`, Docker, the setup wizard, provider selection, and tool registration into one portable installation flow.
- Improved locale synchronization and documented that locale files also contain runtime NLP resources.
- Tightened model-response parsing and prompt guards across agents and tools.

## Fixed

- Portable bootstrap and registry drift issues.
- Setup wizard and Docker startup inconsistencies.
- Multimodal model responses returning lists instead of plain text.
- JSON extraction failures when models included conversational text around structured output.
- Generated skill registration targeting the wrong list in `tools/system.py`.
- Context extraction errors that could leave stale work or location state active.
- Duplicate memory drift and list prompt edge cases.
- Recipe context handling and Home Agent tool guards.
- Security and privacy gaps around local configuration, runtime files, and setup exposure.

## Upgrade notes

Version 2.0.0 is a major release because installation and configuration have been redesigned around portability.

Before updating an existing installation:

1. Back up your local `.env`, credentials, SQLite databases, `chroma_db/`, uploads, and custom prompts.
2. Pull the latest code.
3. Compare your configuration with `.env.example`.
4. Rebuild the container:

   ```bash
   docker compose down
   docker compose up --build -d
   ```

Existing local data remains in the project folder through volume mapping, but backups are strongly recommended before every major upgrade.

## Requirements

- Docker Desktop for the recommended installation path.
- Credentials or an API key for at least one supported AI provider.
- Optional credentials for integrations such as Telegram, Google services, GitHub, Spotify, and others.

## Important privacy note

Astakos is local-first, not fully offline. Long-term memory and runtime state remain on the user's machine, while prompts, media, and tool payloads may be sent to the external model provider or integration required by the enabled feature.
