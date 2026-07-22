# ── Ducked Engine ─────────────────────────────────────────────────
# Developer workflow shortcuts

.PHONY: dev install test lint traefik traefik-down clean help

# ── Default target ────────────────────────────────────────────────

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ── Development ───────────────────────────────────────────────────

dev: ## Start the Ducked engine (backend)
	cd backend && python main.py

install: ## Install Python dependencies
	cd backend && pip install -r requirements.txt

# ── Testing ───────────────────────────────────────────────────────

test: ## Run unit tests
	cd backend && python -m pytest tests/ -v

test-cov: ## Run tests with coverage report
	cd backend && python -m pytest tests/ -v --cov=. --cov-report=term-missing

# ── Linting ───────────────────────────────────────────────────────

lint: ## Run linting checks
	cd backend && python -m py_compile main.py
	cd backend && python -m py_compile config.py
	cd backend && python -m py_compile models.py
	cd backend && python -m py_compile services/github_service.py
	cd backend && python -m py_compile services/docker_service.py

# ── Infrastructure ────────────────────────────────────────────────

traefik: ## Start Traefik reverse proxy (docker compose)
	docker compose up -d

traefik-down: ## Stop Traefik reverse proxy
	docker compose down

# ── Cleanup ───────────────────────────────────────────────────────

clean: ## Remove all ducked Docker resources and temp files
	@echo "🧹 Cleaning ducked containers..."
	@docker ps -a --filter "label=ducked.managed" -q | xargs -r docker rm -f 2>/dev/null || true
	@echo "🧹 Cleaning ducked images..."
	@docker images --filter "label=ducked.managed" -q | xargs -r docker rmi -f 2>/dev/null || true
	@echo "🧹 Cleaning temp directories..."
	@rm -rf /tmp/ducked_* 2>/dev/null || true
	@echo "✅ Clean complete."
