#!/bin/sh
# One-shot installer for the BDDS DDI Activity stack (Kafka + ELK + Kafka UI) on an Ubuntu/Linux Docker host.
# Usage:  ./install.sh [HOST_IP]
set -e
cd "$(dirname "$0")"

command -v docker >/dev/null || { echo "docker not found"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "docker compose v2 plugin not found"; exit 1; }

# Elasticsearch needs vm.max_map_count >= 262144
cur=$(sysctl -n vm.max_map_count 2>/dev/null || echo 0)
if [ "$cur" -lt 262144 ]; then
  echo "Setting vm.max_map_count=262144 (was $cur)"
  sysctl -w vm.max_map_count=262144 >/dev/null
  echo "vm.max_map_count=262144" > /etc/sysctl.d/99-elk.conf
fi

# .env
if [ ! -f .env ]; then
  cp .env.example .env
  ip="${1:-$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p')}"
  [ -n "$ip" ] || { echo "Cannot detect IP; run ./install.sh <HOST_IP>"; exit 1; }
  sed -i "s/^HOST_IP=.*/HOST_IP=$ip/" .env
  echo "Created .env with HOST_IP=$ip  (edit .env to change heap sizes / ports / retention)"
fi
# files edited on Windows may carry CRLF
sed -i 's/\r$//' setup/setup.sh setup/template.json logstash/pipelines/*.conf logstash/pipelines.yml kibana/import.sh

docker compose up -d
. ./.env
sh kibana/import.sh "http://localhost:${KIBANA_PORT:-5601}"

cat <<EOF

Done.
  Kibana    http://$HOST_IP:${KIBANA_PORT:-5601}
  Kafka UI  http://$HOST_IP:${KAFKA_UI_PORT:-8082}
  BDDS Kafka sink:  bootstrap server $HOST_IP:${KAFKA_PORT:-9094}
    topics: activity-dns, activity-dhcp, statistics-dns, statistics-dhcp   key field: key
EOF
