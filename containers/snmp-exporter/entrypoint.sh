#!/bin/sh
set -eu

escape_sed_replacement() {
  printf '%s' "$1" | sed 's/[&|]/\\&/g'
}

snmp_community="${SNMP_COMMUNITY:-public}"

sed \
  -e "s|__SNMP_COMMUNITY__|$(escape_sed_replacement "$snmp_community")|g" \
  /etc/snmp_exporter/auth.yml.tmpl > /etc/snmp_exporter/auth.yml

exec /bin/snmp_exporter \
  --config.file=/etc/snmp_exporter/snmp.yml \
  --config.file=/etc/snmp_exporter/auth.yml \
  --web.listen-address=:9116
