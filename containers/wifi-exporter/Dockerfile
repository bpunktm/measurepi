FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl iproute2 iputils-ping iw procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY wifi_exporter.py /app/wifi_exporter.py

EXPOSE 9721
CMD ["python", "/app/wifi_exporter.py"]
