FROM python:3.11-slim

WORKDIR /app

# Install curl for healthchecks
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY services/layer6_audit/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY shared /app/shared
COPY services/layer6_audit /app/services/layer6_audit

ENV PYTHONPATH=/app

CMD ["python", "-m", "services.layer6_audit.service"]
