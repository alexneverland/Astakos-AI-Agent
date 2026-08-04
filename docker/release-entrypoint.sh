#!/bin/sh
set -eu

mkdir -p /app

# Refresh application code from the immutable image while preserving user data.
# Release users should treat /app as managed runtime storage, not as a source checkout.
rsync -a --delete \
  --exclude '.env' \
  --exclude '*.db' \
  --exclude '*.db-*' \
  --exclude '*.sqlite' \
  --exclude '*.sqlite3' \
  --exclude 'chroma_db/' \
  --exclude 'logs/' \
  --exclude 'telegram_uploads/' \
  --exclude 'telegram_photos/' \
  --exclude 'watch_folder/' \
  --exclude 'outputs/' \
  --exclude 'tmp/' \
  --exclude '_cleaner_backups/' \
  --exclude 'credentials/' \
  --exclude 'credentials*.json' \
  --exclude 'token*.json' \
  --exclude 'astakos_settings.json' \
  --exclude 'astakos_custom_intents.json' \
  --exclude 'astakos_routines.json' \
  --exclude 'persona.md' \
  --exclude 'last_location.json' \
  --exclude 'runtime_snapshot.json' \
  --exclude 'runtime_memory_context.json' \
  --exclude 'linkedin_draft.json' \
  --exclude '.astakos_token' \
  --exclude '.calendar_briefing_sent' \
  --exclude '.ai_briefing_sent' \
  --exclude '.fit_briefing_sent' \
  --exclude '.goal_followup_sent' \
  --exclude '.hn_briefing_sent' \
  --exclude 'run_telegram.lock' \
  --exclude '__pycache__/' \
  /opt/astakos/ /app/

cd /app
exec python boot.py --server
