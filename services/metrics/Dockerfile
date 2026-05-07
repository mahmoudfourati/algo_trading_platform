# Purpose: Image for metrics-service (FastAPI app exposing /metrics).
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app

ENV METRICS_SERVICE_PORT=9100

EXPOSE 9100

CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${METRICS_SERVICE_PORT:-9100}"]
