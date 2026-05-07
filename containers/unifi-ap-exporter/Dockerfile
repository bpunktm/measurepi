FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends snmp \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pyyaml

WORKDIR /app
COPY unifi_ap_exporter.py /app/unifi_ap_exporter.py

EXPOSE 9726
CMD ["python", "/app/unifi_ap_exporter.py"]
