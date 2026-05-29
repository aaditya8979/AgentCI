# API Reference

AgentCI exposes a REST API for managing evaluation runs programmatically.

## Authentication

All `/api/*` endpoints require an API key:

```bash
curl -H "X-API-Key: your-key" http://localhost:8000/api/runs
```

## Endpoints

### Health Check

```
GET /health
```

No authentication required. Returns service health status.

**Response (200):**
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

---

### List Evaluation Runs

```
GET /api/runs
```

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `repo` | string | — | Filter by repository |
| `limit` | int | 50 | Max results |
| `offset` | int | 0 | Pagination offset |

**Response (200):**
```json
[
    {
        "id": "uuid",
        "repo_full_name": "owner/repo",
        "commit_sha": "abc123...",
        "pr_number": 42,
        "status": "completed",
        "final_score": 0.92,
        "overall_passed": true,
        "created_at": "2025-01-01T00:00:00Z"
    }
]
```

---

### Get Evaluation Run

```
GET /api/runs/{run_id}
```

Returns full details including scenario results.

---

### Get Statistics

```
GET /api/stats
```

Returns aggregate statistics across all evaluation runs.

---

### Get Trend Data

```
GET /api/trends
```

Returns historical score data for charting.

---

### Webhook

```
POST /webhook/github
```

GitHub webhook receiver. Requires valid `X-Hub-Signature-256` header.

---

### WebSocket — Live Progress

```
WS /ws/runs/{run_id}
```

Streams real-time evaluation progress events:

```json
{
    "type": "scenario_completed",
    "scenario_id": "greeting",
    "score": 0.92,
    "progress": 0.5
}
```
