# Context Brain Memory Lab — API image (DX-1 onboarding stack).
# Deterministic baseline: no provider keys required; providers are opt-in via env.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install the package (source of truth for dependencies: pyproject.toml).
COPY pyproject.toml README.md /app/
COPY memory_lab /app/memory_lab
RUN pip install --no-cache-dir /app

# Migrations + scripts ship in the image so one-shot compose services can reuse it.
COPY migrations /app/migrations
COPY scripts /app/scripts

EXPOSE 8000
CMD ["uvicorn", "memory_lab.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
