SHELL := /bin/bash

PYTHON ?= python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
REQUIREMENTS_STAMP := $(VENV)/.local-api-requirements.stamp

export AWS_ACCESS_KEY_ID := minioadmin
export AWS_SECRET_ACCESS_KEY := minioadmin
export AWS_REGION := ap-northeast-1
export AWS_DEFAULT_REGION := ap-northeast-1
export AWS_EC2_METADATA_DISABLED := true
export AWS_ENDPOINT_URL_DYNAMODB := http://127.0.0.1:8001
export AWS_ENDPOINT_URL_S3 := http://127.0.0.1:9000
export ENVIRONMENT := local
export WHISKEYS_TABLE := WhiskeySearch-local
export WHISKEY_SEARCH_TABLE := WhiskeySearch-local
export REVIEWS_TABLE := Reviews-local
export DRINK_LOGS_TABLE := DrinkLogs-local
export APP_STATE_TABLE := AppState-local
export IMAGES_BUCKET := whiskey-images-local
export ALLOWED_ORIGINS := http://localhost:3000
export MOCK_AUTH ?= 1
unexport AWS_PROFILE
unexport AWS_DEFAULT_PROFILE
unexport AWS_SESSION_TOKEN
unexport AWS_ROLE_ARN
unexport AWS_WEB_IDENTITY_TOKEN_FILE
unexport AWS_CONTAINER_CREDENTIALS_RELATIVE_URI
unexport AWS_CONTAINER_CREDENTIALS_FULL_URI
unexport AWS_ENDPOINT_URL

.PHONY: local-up local-init local-aggregate api local-down

$(VENV_PYTHON):
	$(PYTHON) -m venv $(VENV)

$(REQUIREMENTS_STAMP): local_api/requirements.txt | $(VENV_PYTHON)
	$(VENV_PYTHON) -m pip install --disable-pip-version-check -r local_api/requirements.txt
	touch $(REQUIREMENTS_STAMP)

local-up:
	docker compose up -d
	@for attempt in $$(seq 1 60); do \
		dynamodb_status=$$(docker inspect --format '{{.State.Health.Status}}' "$$(docker compose ps -q dynamodb-local)" 2>/dev/null || true); \
		minio_status=$$(docker inspect --format '{{.State.Health.Status}}' "$$(docker compose ps -q minio)" 2>/dev/null || true); \
		init_status=$$(docker inspect --format '{{.State.Status}}:{{.State.ExitCode}}' "$$(docker compose ps -a -q minio-init)" 2>/dev/null || true); \
		if [[ "$$dynamodb_status" == healthy && "$$minio_status" == healthy && "$$init_status" == exited:0 ]]; then \
			echo "local services are healthy and whiskey-images-local exists"; \
			exit 0; \
		fi; \
		sleep 1; \
	done; \
	docker compose ps; \
	echo "local services did not become ready within 60 seconds" >&2; \
	exit 1

local-init: $(REQUIREMENTS_STAMP)
	@for attempt in $$(seq 1 10); do \
		if $(VENV_PYTHON) scripts/local/init_tables.py; then break; fi; \
		if [[ $$attempt -eq 10 ]]; then echo "table initialization failed after 10 attempts" >&2; exit 1; fi; \
		sleep 2; \
	done
	$(VENV_PYTHON) scripts/local/seed_whiskeys.py --target local
	$(MAKE) local-aggregate

local-aggregate: $(REQUIREMENTS_STAMP)
	$(VENV_PYTHON) -m local_api.main --aggregate

api: $(REQUIREMENTS_STAMP)
	$(VENV_PYTHON) -m uvicorn local_api.main:app --host 127.0.0.1 --port 8000 --reload

local-down:
	docker compose down
