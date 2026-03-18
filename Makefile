BACKEND_DIR  := backend
FRONTEND_DIR := frontend
OPENAPI_JSON := $(BACKEND_DIR)/openapi.json

.PHONY: help \
        backend frontend \
        export-schema generate-client openapi \
        install install-backend install-frontend \
        update update-backend update-frontend \
        format format-backend format-frontend \
        test test-backend test-frontend

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
	@echo ""
	@echo "  Testing"
	@echo "    test               Test all (backend + frontend)"
	@echo "    test-backend       Test back end"
	@echo "    test-frontend      Test front end"

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
		uv run basedpyright; \
	}

lint-frontend:
	- cd $(FRONTEND_DIR) && { \
		pnpm lint; \
		pnpm tsc:check; \
	}

format: format-backend format-frontend

format-backend:
	cd $(BACKEND_DIR) && uv run ruff format

format-frontend:
	cd $(FRONTEND_DIR) && pnpm format

test: test-backend test-frontend

test-backend:
	cd $(BACKEND_DIR) && uv run pytest --cov app --cov-report term-missing

test-frontend:
	cd $(FRONTEND_DIR) && pnpm test
