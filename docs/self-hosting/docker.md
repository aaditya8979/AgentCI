# Docker Compose Deployment

Deploy the full AgentCI stack with one command.

## Prerequisites

- Docker & Docker Compose v2+
- At least one LLM API key
- [ngrok](https://ngrok.com) for webhook tunneling (development only)

## Quick Start

```bash
git clone https://github.com/aaditya8979/AgentCI.git
cd AgentCI

# Create your environment configuration
cp .env.example .env
# Edit .env — fill in your API keys and secrets

# Start everything
cd docker
docker compose up -d --build
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| **api** | 8000 | FastAPI server — webhooks, REST API, health checks |
| **worker** | — | Temporal worker — executes eval activities |
| **dashboard** | 3000 | Next.js — real-time evaluation dashboard |
| **postgres** | 5432 | PostgreSQL — eval runs, results, baselines |
| **redis** | 6379 | Redis — pub/sub, rate limiting, caching |
| **temporal** | 7233 | Temporal server — workflow orchestration |
| **temporal-ui** | 8080 | Temporal UI — workflow inspector |

## Health Check

```bash
curl http://localhost:8000/health | python3 -m json.tool
```

All checks should show `"ok"`:

```json
{
    "status": "ok",
    "checks": {
        "api": "ok",
        "version": "0.2.0",
        "database": "ok",
        "redis": "ok",
        "temporal": "ok"
    }
}
```

## Connecting to GitHub

See [GitHub App Setup →](github-app.md)

## Useful Commands

```bash
# View logs
docker compose logs -f api worker

# Restart after .env changes
docker compose restart api worker

# Stop everything
docker compose down

# Stop and delete all data
docker compose down -v
```
