#!/bin/sh
set -eu

mkdir -p /app

# Preserve a token supplied by an older release configuration before switching
# Workspace OAuth persistence to the dedicated volume configured by new Compose.
# Image-only upgrades keep using their existing credential path unchanged.
legacy_token_path="/app/credentials/token.json"
if [ -n "${ASTAKOS_TOKEN_PATH:-}" ]; then
  workspace_token_path="$ASTAKOS_TOKEN_PATH"
else
  workspace_token_path="/app/workspace_oauth/token.json"
fi
export ASTAKOS_TOKEN_PATH="$workspace_token_path"

if [ ! -s "$workspace_token_path" ] && [ -s "$legacy_token_path" ]; then
  mkdir -p "$(dirname "$workspace_token_path")"
  (
    umask 077
    cp "$legacy_token_path" "$workspace_token_path"
  )
  chmod 600 "$workspace_token_path"
fi

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
  --exclude 'workspace_oauth/' \
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
