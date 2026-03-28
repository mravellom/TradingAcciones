# Deployment Guide

## Prerequisites

- Python 3.11+
- Node.js 20+
- Docker & Docker Compose
- PostgreSQL 16 (or use Docker)
- Redis 7 (or use Docker)

## Local Development

### 1. Backend

```bash
cd backend
cp .env.example .env          # Edit with your values
python -m venv .venv
source .venv/bin/activate
pip install -e .
alembic upgrade head          # Run migrations
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm start                     # Serves on http://localhost:4200
```

### 3. Infrastructure (Docker)

```bash
cd backend
docker compose up -d postgres redis   # Just DB + Redis
```

Or use the Makefile:

```bash
make docker-up    # Full stack via Docker
make dev          # Backend + Frontend locally
```

## Docker Deployment

### Development

```bash
cd backend
docker compose up -d
```

This starts PostgreSQL, Redis, and the app. The app reads from `.env`.

### Production

```bash
# 1. Create secrets directory
mkdir -p backend/secrets
echo "postgresql+asyncpg://trading:SECURE_PASSWORD@postgres:5432/trading_db" > backend/secrets/database_url.txt
echo "your-secure-api-key" > backend/secrets/api_key.txt
echo "your-binance-key" > backend/secrets/binance_api_key.txt
echo "your-binance-secret" > backend/secrets/binance_api_secret.txt
echo "your-telegram-token" > backend/secrets/telegram_bot_token.txt

# 2. Launch with production overlay
cd backend
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## Environment Variables

See `backend/.env.example` for all available variables. Key ones:

| Variable | Description | Required |
|----------|-------------|----------|
| `EXECUTION_MODE` | `PAPER` or `LIVE` | Yes |
| `DEBUG` | `true`/`false` (controls API docs visibility) | Yes |
| `API_KEY` | Auth key for protected endpoints | LIVE mode |
| `DATABASE_URL` | PostgreSQL connection string | Yes |
| `REDIS_URL` | Redis connection string | Yes |
| `BINANCE_API_KEY` | Binance API key | LIVE mode |
| `BINANCE_API_SECRET` | Binance API secret | LIVE mode |
| `CORS_ORIGINS` | Comma-separated allowed origins | Yes |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token for notifications | Optional |
| `TELEGRAM_CHAT_ID` | Telegram chat ID | Optional |

## Production Checklist

- [ ] `DEBUG=false`
- [ ] `API_KEY` set to a strong random key
- [ ] `CORS_ORIGINS` set to your production domain
- [ ] `EXECUTION_MODE=PAPER` to start (switch to LIVE only after testing)
- [ ] `REQUIRE_MANUAL_APPROVAL=true` recommended for LIVE
- [ ] Secrets managed via Docker Secrets (not plaintext `.env`)
- [ ] SSL/TLS termination (nginx/Caddy/cloud LB in front)
- [ ] Database backups configured
- [ ] Rate limiting active (default: 60 req/min)
- [ ] Monitoring: health endpoint at `/api/v1/system/health`
- [ ] Telegram notifications configured and tested

## Database Migrations

```bash
cd backend
alembic upgrade head              # Apply all migrations
alembic downgrade -1              # Rollback last migration
alembic revision --autogenerate -m "description"  # New migration
```

## Troubleshooting

**Database connection refused:**
- Check PostgreSQL is running: `docker compose ps`
- Verify `DATABASE_URL` matches Docker port mapping (default: 5434 external, 5432 internal)

**Redis connection refused:**
- Check Redis is running: `docker compose ps`
- Default port: 6381 external, 6379 internal

**Binance API errors:**
- Start with `BINANCE_TESTNET=true`
- Verify API key has correct permissions (spot trading)
- Check rate limits: the app has built-in Binance rate limiting (1100 req/min)

**API docs not showing:**
- Docs are only available when `DEBUG=true`
- Access at `/docs` (Swagger) or `/redoc` (ReDoc)

**Circuit breaker activated:**
- Check status: `GET /api/v1/risk/circuit-breaker`
- Reset: `POST /api/v1/risk/circuit-breaker/reset` (requires API key)
