# Purpose: Image for metrics-service (FastAPI app exposing /metrics).
FROM python:3.11-slim

WORKDIR /app

# Install curl for healthchecks
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY services/metrics/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy the shared module from parent context
COPY shared /app/shared

COPY services/metrics/app /app/app

ENV METRICS_SERVICE_PORT=9100

EXPOSE 9100

CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${METRICS_SERVICE_PORT:-9100}"]
