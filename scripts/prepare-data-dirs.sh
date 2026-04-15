#!/usr/bin/env sh
set -eu

BASE_DIR="${1:-$(pwd)}"
DATA_DIR="$BASE_DIR/data"

mkdir -p "$DATA_DIR/prometheus" "$DATA_DIR/grafana" "$DATA_DIR/wifi-exporter"

chown -R 65534:65534 "$DATA_DIR/prometheus"
chmod -R u+rwX,g+rwX,o-rwx "$DATA_DIR/prometheus"

chown -R 0:0 "$DATA_DIR/wifi-exporter"
chmod -R u+rwX,go-rwx "$DATA_DIR/wifi-exporter"

echo "Prepared persistent data directories under: $DATA_DIR"
