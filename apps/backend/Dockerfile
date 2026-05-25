FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Layer 1: shared package (changes rarely)
COPY packages/shared /app/packages/shared
RUN pip install --no-cache-dir -e /app/packages/shared

# Layer 2: requirements (changes occasionally)
COPY apps/backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Layer 3: code (changes constantly)
COPY apps/backend /app/apps/backend

WORKDIR /app/apps/backend

EXPOSE 8000

# Migrations run on every start — idempotent, serialized by Postgres advisory lock
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
