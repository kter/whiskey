.PHONY: help up down build logs shell test migrate init-db clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

up: ## Start all services
	./dev.sh up

down: ## Stop all services
	./dev.sh down

build: ## Rebuild all services
	./dev.sh build

logs: ## Show logs from all services
	./dev.sh logs

shell: ## Open a shell in the backend container
	./dev.sh shell

test: ## Run backend tests
	./dev.sh test

migrate: ## Run database migrations
	./dev.sh migrate

init-db: ## Initialize database with test data
	./dev.sh init-db

clean: ## Remove all containers and volumes
	docker-compose down -v 