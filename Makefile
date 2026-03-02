BACKEND_DIR  := backend
FRONTEND_DIR := frontend
OPENAPI_JSON := $(BACKEND_DIR)/openapi.json

.PHONY: help \
        backend frontend \
        export-schema generate-client openapi \
        install install-backend install-frontend \
        update update-backend update-frontend \
        format format-backend format-frontend

help:
	@echo ""
	@echo "Usage: make <target>"
	@echo ""
	@echo "  Development servers"
	@echo "    backend            Run the FastAPI dev server"
	@echo "    frontend           Run the Vite dev server"
	@echo ""
	@echo "  OpenAPI client generation"
	@echo "    export-schema      Export openapi.json from FastAPI"
	@echo "    generate-client    Generate TypeScript client from openapi.json"
	@echo "    openapi            Run the full pipeline (export + generate)"
	@echo ""
	@echo "  Dependencies"
	@echo "    install            Install all dependencies (backend + frontend)"
	@echo "    install-backend    Install Python dependencies via uv"
	@echo "    install-frontend   Install Node.js dependencies via pnpm"
	@echo ""
	@echo "    update             Update all dependencies (backend + frontend)"
	@echo "    update-backend     Update Python dependencies via uv"
	@echo "    update-frontend    Update Node.js dependencies via pnpm"
	@echo ""
	@echo "  Linting"
	@echo "    lint               Lint all (backend + frontend)"
	@echo "    lint-backend       Lint back end"
	@echo "    lint-frontend      Lint front end"
	@echo ""
	@echo "  Formatting"
	@echo "    format             Format all (backend + frontend)"
	@echo "    format-backend     Format back end"
	@echo "    format-frontend    Format front end"

backend:
	cd $(BACKEND_DIR) && uv run fastapi dev

frontend:
	cd $(FRONTEND_DIR) && pnpm dev

export-schema:
	cd $(BACKEND_DIR) && uv run python export_openapi.py

generate-client: $(OPENAPI_JSON)
	cd $(FRONTEND_DIR) && pnpm generate-client

openapi: export-schema generate-client

$(OPENAPI_JSON): $(BACKEND_DIR)/app/main.py $(BACKEND_DIR)/export_openapi.py
	cd $(BACKEND_DIR) && uv run python export_openapi.py

install: install-backend install-frontend

install-backend:
	cd $(BACKEND_DIR) && uv sync

install-frontend:
	cd $(FRONTEND_DIR) && pnpm install

update: update-backend update-frontend

update-backend:
	cd $(BACKEND_DIR) && uv sync -U

update-frontend:
	cd $(FRONTEND_DIR) && pnpm update

lint: lint-backend lint-frontend

lint-backend:
	- cd $(BACKEND_DIR) && { \
		uv run ruff check; \
		uv run ty check; \
		uv run flake8 .; \
		uv run pylint app notebooks; \
		uv run mypy; \
	}

lint-frontend:
	- cd $(FRONTEND_DIR) && { \
		pnpm lint; \
		pnpm tsc:check; \
	}

format: format-backend format-frontend

format-backend:
	cd $(BACKEND_DIR) && uv run isort . && uv run black .

format-frontend:
	cd $(FRONTEND_DIR) && pnpm format
