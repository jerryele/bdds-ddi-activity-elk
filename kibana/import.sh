#!/bin/sh
# Import data views + dashboards into Kibana (idempotent: overwrite=true).
# Usage: ./import.sh [kibana_url]      default http://localhost:5601
set -e
KB="${1:-http://localhost:${KIBANA_PORT:-5601}}"
DIR="$(cd "$(dirname "$0")" && pwd)"

printf 'Waiting for Kibana at %s ' "$KB"
for i in $(seq 1 90); do
  if curl -sf "$KB/api/status" | grep -q '"level":"available"'; then echo ok; break; fi
  printf '.'; sleep 5
  [ "$i" = 90 ] && { echo " timed out"; exit 1; }
done

# data views first: dashboards reference them by id
for f in data-views.ndjson dns-dashboard.ndjson dhcp-dashboard.ndjson stats-dashboards.ndjson; do
  printf 'Importing %-28s' "$f"
  curl -s -XPOST "$KB/api/saved_objects/_import?overwrite=true" -H 'kbn-xsrf: true' \
       --form file=@"$DIR/$f" | python3 -c 'import sys,json; r=json.load(sys.stdin); print("ok (%d objects)" % r["successCount"] if r.get("success") else "FAILED: %s" % r.get("errors"))'
done
