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
  --exclude 'uploads/' \
  --exclude 'generated_files/' \
  --exclude 'credentials/' \
  --exclude 'credentials*.json' \
  --exclude 'token*.json' \
  --exclude 'backups/' \
  --exclude 'data/' \
  --exclude 'runtime/' \
  --exclude '__pycache__/' \
  /opt/astakos/ /app/

cd /app
exec python boot.py --server
