SHELL := /bin/bash

PYTHON ?= python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
REQUIREMENTS_STAMP := $(VENV)/.local-api-requirements.stamp

# Local service settings must not leak into the CI checks (which use moto).
ifeq ($(filter check,$(MAKECMDGOALS)),)
export AWS_ACCESS_KEY_ID := minioadmin
export AWS_SECRET_ACCESS_KEY := minioadmin
export AWS_REGION := ap-northeast-1
export AWS_DEFAULT_REGION := ap-northeast-1
export AWS_EC2_METADATA_DISABLED := true
export AWS_ENDPOINT_URL_DYNAMODB := http://127.0.0.1:5000
export AWS_ENDPOINT_URL_S3 := http://127.0.0.1:5000
export ENVIRONMENT := local
export WHISKEY_SEARCH_TABLE := WhiskeySearch-local
export DRINKLOGS_TABLE := DrinkLogs-local
export APP_STATE_TABLE := AppState-local
export IMAGES_BUCKET := whiskey-images-local
export ALLOWED_ORIGINS := http://localhost:3000
export MOCK_AUTH ?= 1
endif

unexport AWS_PROFILE
unexport AWS_DEFAULT_PROFILE
unexport AWS_SESSION_TOKEN
unexport AWS_ROLE_ARN
unexport AWS_WEB_IDENTITY_TOKEN_FILE
unexport AWS_CONTAINER_CREDENTIALS_RELATIVE_URI
unexport AWS_CONTAINER_CREDENTIALS_FULL_URI
unexport AWS_ENDPOINT_URL

.PHONY: local-up local-init api local-down check

$(VENV_PYTHON):
	$(PYTHON) -m venv $(VENV)

$(REQUIREMENTS_STAMP): local_api/requirements.txt | $(VENV_PYTHON)
	$(VENV_PYTHON) -m pip install --disable-pip-version-check -r local_api/requirements.txt
	touch $(REQUIREMENTS_STAMP)

local-up: $(REQUIREMENTS_STAMP)
	$(VENV_PYTHON) scripts/local/moto_server.py start

local-init: $(REQUIREMENTS_STAMP)
	@for attempt in $$(seq 1 10); do \
		if $(VENV_PYTHON) scripts/local/init_tables.py; then break; fi; \
		if [[ $$attempt -eq 10 ]]; then echo "table initialization failed after 10 attempts" >&2; exit 1; fi; \
		sleep 2; \
	done
	$(VENV_PYTHON) scripts/local/init_bucket.py
	$(VENV_PYTHON) scripts/local/seed_whiskeys.py --target local

api: $(REQUIREMENTS_STAMP)
	$(VENV_PYTHON) -m uvicorn local_api.main:app --host 127.0.0.1 --port 8000 --reload

local-down:
	$(VENV_PYTHON) scripts/local/moto_server.py stop

check:
	@for path in $(VENV_PYTHON) infra/node_modules frontend/node_modules; do \
		if [ ! -e "$$path" ]; then \
			echo "missing $$path: run 'bash scripts/agent/setup.sh' first" >&2; exit 1; \
		fi; \
	done
	$(VENV_PYTHON) -m pytest tests
	cd infra && npm run build
	cd infra && npx jest
	cd infra && npm run synth:dev -- --quiet
	cd frontend && npm run lint
	cd frontend && npm run typecheck
	cd frontend && npx vitest run
