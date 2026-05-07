FROM python:3.11-slim

WORKDIR /app

COPY requirements-ml.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-ml.txt -r requirements-dev.txt

COPY . .

CMD ["python", "-m", "services.layer5_execution.service"]
