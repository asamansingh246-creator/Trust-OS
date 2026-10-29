FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app
EXPOSE 8000

CMD ["sh", "-c", "python -m app.seed_and_synthetic && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
