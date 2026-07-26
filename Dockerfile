# Single image for the Mira agent (ADR-047 runtime layer).
#
# The same image runs as a local container or on AWS / EKS / EKS-Anywhere — the
# deployment *platform* is a Helm/manifest concern that injects env, never baked in.
# All configuration is 12-factor env: DEPLOYMENT_PROFILE (default-set), PLATFORM (infra
# bundle), LLM_BASE_URL/LLM_API_KEY/LLM_MODEL (model), MCP_SERVERS/MCP_BASE_URL (tools).
#
# Extras: [llm] (OpenAI-compatible provider) + [mcp] (MCP tool discovery). Drop them for a
# minimal echo-stub image. boto3/aws extras are added when the AWS provider is implemented.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# Install dependencies first (separate layer) for build caching.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[llm,mcp,otel]"

# Demo agent-card registry fixtures (handbook.md + ledger.csv): the __main__
# entrypoint loads them ONLY when tests/fixtures/ exists relative to the cwd, so
# /turn routes supervisor-first (grounded specialist answers) instead of the
# plain runtime turn. Copied read-only; drop this layer for a minimal image.
COPY tests/fixtures ./tests/fixtures

# Non-root runtime user. /data is the durable-persistence mount (MIRA_DATA_DIR)
# — create it owned by mira so an EMPTY named volume inherits that ownership on
# first mount (Docker copies the image mountpoint's uid/gid), letting the
# non-root process open mira.db. Without this the fresh volume mounts root-owned
# and sqlite fails with "unable to open database file".
RUN useradd --create-home --uid 10001 mira \
    && mkdir -p /data \
    && chown -R mira:mira /app /data
USER mira

EXPOSE 8080

# Serve the warm service + runtime. Host 0.0.0.0 so the container is reachable; the
# process reads all other config from env at boot. WORKDIR /app is the cwd so the
# demo fixtures above are discovered.
CMD ["python", "-m", "mira", "--host", "0.0.0.0", "--port", "8080"]
