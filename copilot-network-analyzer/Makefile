VENV ?= .venv
PY := $(VENV)/bin/python
GATEWAY_HOST ?= REPLACE-WITH-YOUR-PUBLIC-HOSTNAME

.PHONY: help setup test run connector probe smoke docker clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-10s %s\n", $$1, $$2}'

setup: ## Create the virtualenv and install dev dependencies
	python3 -m venv $(VENV)
	$(PY) -m pip install -q -r gateway/requirements-dev.txt

test: ## Run the gateway test suite (no ntopng needed)
	cd gateway && ../$(PY) -m pytest -q

run: ## Run the gateway locally on :8800
	$(PY) -m uvicorn app.main:app --app-dir gateway --host 127.0.0.1 --port 8800 --reload

connector: ## Regenerate the custom connector definition
	$(PY) scripts/build_connector.py --host $(GATEWAY_HOST)

probe: ## Check which ntopng REST endpoints your deployment serves
	./scripts/probe-ntopng.sh

smoke: ## Call every gateway operation end to end
	./scripts/smoke-test.sh

docker: ## Build and start the gateway container
	docker compose up -d --build

clean:
	rm -rf $(VENV) .pytest_cache gateway/.pytest_cache
	find . -name __pycache__ -type d -exec rm -rf {} +
