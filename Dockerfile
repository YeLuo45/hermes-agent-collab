# ── Builder stage ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Install deps to user home (--user) to avoid system-wide install
RUN pip install --no-cache-dir --user -r requirements.txt


# ── Runtime stage ──────────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Install runtime OS deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home hermes

# Copy installed Python packages from builder
COPY --from=builder /root/.local /home/hermes/.local

# Copy application code
COPY --chown=hermes:hermes collaboration/ /app/collaboration/
COPY --chown=hermes:hermes hermes_agent_collab/ /app/hermes_agent_collab/
COPY --chown=hermes:hermes dashboard/ /app/dashboard/
COPY --chown=hermes:hermes docs/ /app/docs/
COPY --chown=hermes:hermes cli.py /app/cli.py
COPY --chown=hermes:hermes requirements.txt /app/requirements.txt

# Hermes data directory
ENV HERMES_HOME=/home/hermes/.hermes
RUN mkdir -p $HERMES_HOME/workspaces

USER hermes
ENV PATH=/home/hermes/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/monitor/health || exit 1

EXPOSE 8000

ENTRYPOINT ["python", "-m", "uvicorn"]
CMD ["collaboration.collab_api:app", "--host", "0.0.0.0", "--port", "8000"]
