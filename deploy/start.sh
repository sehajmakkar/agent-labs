#!/bin/sh
# Start the hosted lab. On the first boot (or on a host without a persistent disk) the trace store
# is created from the snapshot made with `lab snapshot`, so the demo opens with real runs in it.
set -e
DB="${AGENTLAB_DB:-/data/lab.db}"
mkdir -p "$(dirname "$DB")"
if [ ! -f "$DB" ] && [ -f deploy/seed.db.gz ]; then
  echo "seeding $DB from deploy/seed.db.gz"
  gunzip -c deploy/seed.db.gz > "$DB"
fi
exec uv run --no-sync lab ui --host 0.0.0.0 --port "${PORT:-8000}"
