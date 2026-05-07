FROM prom/snmp-exporter:v0.26.0

COPY --chmod=755 entrypoint.sh /entrypoint.sh
COPY auth.yml.tmpl /etc/snmp_exporter/auth.yml.tmpl

ENTRYPOINT ["/entrypoint.sh"]
