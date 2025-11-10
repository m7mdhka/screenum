.PHONY: help install install-dev run test lint format clean

help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install production dependencies
	uv sync

install-dev: ## Install development dependencies
	uv sync --dev

run: ## Run the application
	uv run python src/main.py

lint: ## Run linting
	uv run ruff check .

format: ## Format code
	uv run ruff format .

type-check: ## Run type checking
	uv run mypy src/

check: ## Run all checks (lint, format, type-check)
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src/

fix: ## Fix linting issues
	uv run ruff check --fix .
	uv run ruff format .

clean: ## Clean up generated files
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf htmlcov
	rm -rf dist
	rm -rf build

redis: ## Pull and run Redis container
	docker pull redis:latest
	-docker stop redis-dev 2>/dev/null
	-docker rm redis-dev 2>/dev/null
	docker run --name redis-dev -p 6379:6379 -d redis:latest
	@echo "Redis is running on localhost:6379"

redis-stop: ## Stop Redis container
	docker stop redis-dev
	docker rm redis-dev