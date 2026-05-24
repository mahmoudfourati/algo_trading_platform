FROM python:3.11-slim

WORKDIR /app

# Install curl for healthchecks
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Copy shared modules
COPY shared/ /app/shared/

# Copy Layer 1 dependencies
COPY services/layer1_consensus/ /app/services/layer1_consensus/
COPY services/layer1_trust/ /app/services/layer1_trust/
COPY services/layer1_hashlog/ /app/services/layer1_hashlog/
COPY services/layer1_validated/ /app/services/layer1_validated/
COPY services/layer1_ingestion/ /app/services/layer1_ingestion/

# Copy merged service
COPY services/layer1_merged/ /app/services/layer1_merged/

# Copy config
COPY config/ /app/config/

# Install dependencies
RUN pip install --no-cache-dir -r /app/services/layer1_merged/requirements.txt

# Create logs directory
RUN mkdir -p /app/logs

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "services.layer1_merged.service"]
