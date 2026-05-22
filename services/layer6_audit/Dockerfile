FROM python:3.11-slim

WORKDIR /app

COPY services/layer6_audit/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY shared /app/shared
COPY services/layer6_audit /app/services/layer6_audit

ENV PYTHONPATH=/app

CMD ["python", "-m", "services.layer6_audit.service"]
