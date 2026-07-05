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
COPY pyproject.toml ./
COPY src ./src
RUN pip install ".[llm,mcp]"

# Non-root runtime user.
RUN useradd --create-home --uid 10001 mira
USER mira

EXPOSE 8080

# Serve the warm service + runtime. Host 0.0.0.0 so the container is reachable; the
# process reads all other config from env at boot.
CMD ["python", "-m", "mira", "--host", "0.0.0.0", "--port", "8080"]
