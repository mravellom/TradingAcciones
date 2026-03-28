.PHONY: dev dev-backend dev-frontend docker-up docker-down test-backend test-frontend build migrate lint

# Local development
dev-backend:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm start

dev:
	$(MAKE) dev-backend & $(MAKE) dev-frontend

# Docker
docker-up:
	cd backend && docker compose up -d

docker-down:
	cd backend && docker compose down

docker-prod:
	cd backend && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Testing
test-backend:
	cd backend && python -m pytest tests/ -v

test-frontend:
	cd frontend && npx ng test --watch=false --browsers=ChromeHeadless

test: test-backend test-frontend

# Build
build:
	cd backend && docker compose build

build-frontend:
	cd frontend && npx ng build --configuration production

# Database
migrate:
	cd backend && alembic upgrade head

migrate-new:
	cd backend && alembic revision --autogenerate -m "$(msg)"

# Linting
lint:
	cd backend && python -m ruff check app/ tests/
	cd frontend && npx ng lint

# Utility
logs:
	cd backend && docker compose logs -f app

shell:
	cd backend && docker compose exec app bash
