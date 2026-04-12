FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY services/layer1_ingestion/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY services /app/services
COPY shared /app/shared
COPY config /app/config

RUN mkdir -p /app/logs

CMD ["python", "-m", "services.layer1_ingestion.run_console"]
