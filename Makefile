.PHONY: setup start smoke test eval lint lint-imports sanitize-check

# Use the project venv if it exists (created by `make setup`), else system python3.
# Lets `make start/smoke/test` work without activating the venv — and avoids
# picking up a stale editable install from another checkout.
PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

# Prefer Python 3.12+ (project requires it); fall back to python3 on PATH.
PY_BOOTSTRAP := $(shell command -v python3.12 >/dev/null && echo python3.12 || echo python3)

# One-time: create a local venv and install the package + dev deps.
# uv-managed Python 3.12 breaks `python3.12 -m venv` (ensurepip / bad pyvenv home);
# use `uv venv` when uv is available.
setup:
	@if command -v uv >/dev/null 2>&1; then \
		uv venv .venv --python 3.12 --seed; \
		uv pip install --python .venv/bin/python -e ".[dev]"; \
	else \
		$(PY_BOOTSTRAP) -m venv .venv; \
		.venv/bin/python -m pip install -e ".[dev]"; \
	fi
	@echo "Done. Run 'make start' to launch the service."

# Start the warm service on 127.0.0.1:8080 (offline 'local' model). Ctrl-C to stop.
start:
	$(PY) -m mira

# With the service running, check health and run one streamed turn.
smoke:
	@curl -sf http://127.0.0.1:8080/health > /dev/null && echo "health: ok" || (echo "service not reachable on :8080 — run 'make start' first" && exit 1)
	@curl -s http://127.0.0.1:8080/health/ready && echo ""
	@$(PY) -c "from mira.providers.local import build_local_bundle; from mira.app import build_app; app=build_app('kubernetes', bundle=build_local_bundle()); print('turn:', app.run_turn('what does the handbook say about middleware ordering?')['response']); print('stream:', [e.kind for e in app.stream_events('show the plan')])"

test:
	$(PY) -m pytest -q

# Offline eval harness (ADR-045): goldens + adversarial seed + trace scoring + gate.
eval:
	$(PY) -m pytest evals -q

lint: lint-imports sanitize-check

lint-imports:
	$(PY) tools/lint_imports.py src/mira src/mira_contracts src/mira_harness

# Guard against upstream-extraction strings reappearing (see tools/sanitize_extract.py).
# Patterns use [ ] character classes so this rule never matches itself.
sanitize-check:
	@! grep -riE '4[7]lining|os[d]u|\bed[i]\b|subsur[f]ace|geosc[i]ence|petre[l]|ppd[m]|seg-?[y]\b|osiso[f]t|rasheedonne[t]|nidhikau[l]|\bsa[a]\b' \
		--exclude-dir=.git --exclude-dir=.venv --exclude-dir=__pycache__ --exclude-dir=.pytest_cache \
		--exclude=sanitize_extract.py . \
		|| (echo "sanitize-check: upstream domain strings found (see matches above)" && exit 1)
	@echo "sanitize-check: ok"
