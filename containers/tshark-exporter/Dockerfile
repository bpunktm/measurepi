FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends tshark ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY tshark_exporter.py /app/tshark_exporter.py

EXPOSE 9723
CMD ["python", "/app/tshark_exporter.py"]
