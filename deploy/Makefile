# Mira agent — standalone local Docker deploy.
#
# Usage:
#   make -C deploy up        build + start Mira (detached) on :8080
#   make -C deploy down      stop + remove
#   make -C deploy logs      follow logs
#   make -C deploy ps        service status
#   make -C deploy health    curl the /health endpoint
#   make -C deploy restart   recreate the container (after an .env.local edit)
#
# Prereq: Vantage's stack must be up first — Mira reaches vantage-mcp on the
# host port :8640. Start Vantage (`make -C ../../vantage/deploy up`), then this.

# Env layering: docker compose auto-reads .env (template defaults); .env.local
# is loaded LAST so it WINS and holds the DeepSeek key/model. The flag is only
# added when .env.local exists, so a bare checkout still boots on the template.
ENV_LOCAL := $(wildcard .env.local)
ENV_FILES := --env-file .env $(if $(ENV_LOCAL),--env-file .env.local)
COMPOSE := docker compose $(ENV_FILES) -f docker-compose.yml

.PHONY: build up down logs ps health restart

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up --build -d
	@echo "mira up: http://localhost:8080/health"

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

restart:
	$(COMPOSE) up -d --force-recreate mira
	@echo "mira recreated: http://localhost:8080/health"

health:
	@echo "mira:"; curl -sf http://localhost:8080/health >/dev/null && echo " ok" || echo " DOWN"
