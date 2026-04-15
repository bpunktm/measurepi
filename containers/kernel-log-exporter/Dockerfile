FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends util-linux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY kernel_log_exporter.py /app/kernel_log_exporter.py

EXPOSE 9722
CMD ["python", "/app/kernel_log_exporter.py"]
