# Purpose: Layer 3 Dockerfile

FROM python:3.11-slim

WORKDIR /app

# Install curl for healthchecks
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY requirements-ml.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-ml.txt -r requirements-dev.txt

COPY . .

CMD ["python", "-m", "services.layer3_strategy.service"]
