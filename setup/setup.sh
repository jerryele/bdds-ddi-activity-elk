#!/bin/sh
set -e
ES=http://elasticsearch:9200
DAYS="${RETENTION_DAYS:-7}"
curl -sf -XPUT $ES/_ilm/policy/activity-7d -H 'Content-Type: application/json' \
  -d "{\"policy\":{\"phases\":{\"hot\":{\"actions\":{}},\"delete\":{\"min_age\":\"${DAYS}d\",\"actions\":{\"delete\":{}}}}}}"
# one template for all activity-* / statistics-* indices
curl -sf -XPUT $ES/_index_template/ddi -H 'Content-Type: application/json' -d @/setup/template.json
echo "setup done (retention ${DAYS}d)"
