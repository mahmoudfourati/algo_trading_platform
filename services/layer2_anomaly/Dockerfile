# Purpose: Image for Layer 2 anomaly scoring (ValidatedTick -> ScoredTick).
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

# Install curl for healthchecks
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY services/layer2_anomaly/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY services /app/services
COPY shared /app/shared
COPY config /app/config

RUN mkdir -p /app/logs /app/artifacts

CMD ["python", "-m", "services.layer2_anomaly.service"]
