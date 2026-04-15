#!/bin/sh
set -eu

escape_sed_replacement() {
  printf '%s' "$1" | sed 's/[&|]/\\&/g'
}

internet_ping_target="${INTERNET_PING_TARGET:-1.1.1.1}"
http_check_url="${HTTP_CHECK_URL:-https://connectivitycheck.gstatic.com/generate_204}"

sed \
  -e "s|__INTERNET_PING_TARGET__|$(escape_sed_replacement "$internet_ping_target")|g" \
  -e "s|__HTTP_CHECK_URL__|$(escape_sed_replacement "$http_check_url")|g" \
  /etc/prometheus/prometheus.yml.tmpl > /etc/prometheus/prometheus.yml

exec /bin/prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/prometheus \
  --web.enable-lifecycle
