FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Layer 1: shared package (changes rarely)
COPY packages/shared /app/packages/shared
RUN pip install --no-cache-dir -e /app/packages/shared

# Layer 2: ingestor package (changes occasionally)
COPY workers/ingestor /app/workers/ingestor
RUN pip install --no-cache-dir -e /app/workers/ingestor

CMD ["ingestor"]
