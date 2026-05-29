# Environment Variables

Complete reference for all AgentCI environment variables.

## Required

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://agentci:agentci_dev@localhost:5432/agentci` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379` |
| `AGENTCI_API_KEYS` | Comma-separated API keys for dashboard auth | `key1,key2` |
| `GITHUB_WEBHOOK_SECRET` | HMAC secret for webhook verification | `openssl rand -hex 20` |

## LLM API Keys (at least one required)

| Variable | Provider |
|----------|----------|
| `OPENAI_API_KEY` | OpenAI (GPT-4o, GPT-4o-mini) |
| `ANTHROPIC_API_KEY` | Anthropic (Claude Sonnet) |
| `GOOGLE_API_KEY` | Google (Gemini Pro) |

## GitHub App

| Variable | Description |
|----------|-------------|
| `GITHUB_APP_ID` | GitHub App ID (from app settings) |
| `GITHUB_INSTALLATION_ID` | Installation ID (from URL after installing) |
| `GITHUB_APP_PRIVATE_KEY` | PEM private key (newlines replaced with `\n`) |

## Temporal

| Variable | Default | Description |
|----------|---------|-------------|
| `TEMPORAL_HOST` | `localhost:7233` | Temporal server address |
| `TEMPORAL_NAMESPACE` | `default` | Temporal namespace |
| `TEMPORAL_TASK_QUEUE` | `agentci-eval` | Worker task queue name |

## Logging

| Variable | Default | Options |
|----------|---------|---------|
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_FORMAT` | `console` | `console` (dev), `json` (production) |

## Rate Limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTCI_RATE_LIMIT` | `20` | Max eval runs per repo per hour |

## Dashboard

| Variable | Default | Description |
|----------|---------|-------------|
| `DASHBOARD_ORIGIN` | `http://localhost:3000` | CORS allowed origin |
