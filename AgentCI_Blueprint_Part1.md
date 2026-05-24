# AgentCI: The Production Blueprint

## A Complete Engineering Playbook for Building an Enterprise-Grade AI Evaluation CI/CD Platform

> *This is not a tutorial. This is the document you read before writing a single line of code. It teaches you the WHY behind every architectural decision, so when you sit down to build, you don't just copy — you understand.*

---

# PART 1: THE PROBLEM, THE VISION, AND THE ARCHITECTURE

---

## Chapter 1: The Problem — Why This Matters More Than You Think

### 1.1 The Fundamental Disconnect

In traditional software engineering, there's a contract between input and output. You call `add(2, 3)`, you get `5`. Every time. This determinism is what makes testing possible. Unit tests, integration tests, end-to-end tests — they all rely on one assumption: **given the same input, the system produces the same output.**

LLMs shatter this assumption.

When you send the prompt *"Summarize this document"* to GPT-4, you get a slightly different summary every time. Not wildly different — but different enough that `assertEqual(output, expected)` will fail 100% of the time. This isn't a bug. It's the fundamental nature of autoregressive token generation with temperature > 0.

**The consequence:** Every tool, framework, and methodology that software engineering has built over 50 years — CI/CD, unit testing, regression suites, code coverage — becomes useless for AI applications overnight.

### 1.2 The Real-World Horror Stories

This isn't theoretical. Here's what actually happens at companies deploying AI agents:

**Scenario 1: The Silent Regression**
A team at a fintech company tweaks their customer support agent's system prompt to be "more empathetic." The change looks innocent. It goes through code review. A human reads the new prompt and says "yeah, that looks more empathetic." They merge. Two weeks later, they discover the agent has been approving refunds it shouldn't — because the "empathetic" prompt made it too agreeable. $2.3M in unauthorized refunds before anyone noticed.

**Scenario 2: The RAG Chunk Disaster**
An engineering team changes their RAG chunk size from 512 tokens to 1024 tokens because a blog post said larger chunks improve context. Their agent's accuracy on simple questions goes up 3%. Their accuracy on multi-step reasoning questions drops 41%. Nobody measured the second metric.

**Scenario 3: The Model Swap Surprise**
A company switches from GPT-4 to GPT-4-turbo to save costs. 90% of their test cases still pass (they check manually). But the 10% that fail are all in the "legal compliance" category. Their agent is now giving incorrect legal advice for a month.

### 1.3 Why Existing Solutions Fall Short

| Tool | What It Does | Why It's Not Enough |
|------|-------------|-------------------|
| **Promptfoo** | CLI tool for prompt testing | No CI/CD integration, no historical baselines, no trace visualization |
| **LangSmith** | LLM observability & tracing | Observability ≠ Testing. Tells you what happened, not whether it's correct |
| **Braintrust** | Eval platform | Enterprise-focused, expensive, not developer-workflow-native |
| **Deepeval** | Python eval framework | Good for local testing, no GitHub integration, no sandbox isolation |
| **Arize Phoenix** | Open-source observability | Tracing & monitoring, not gating PRs based on quality regressions |

**The gap:** None of these tools sit *inside your CI/CD pipeline* and act as a **quality gate** that blocks broken AI changes from reaching production.

### 1.4 What Makes AgentCI Remarkable

AgentCI is not "another eval tool." It's the **missing infrastructure layer** between "I changed my prompt" and "my agent is deployed."

1. **GitHub-native quality gate.** Blocks the PR *before* merge, not a dashboard you check after.
2. **LLM-as-a-Judge with consensus voting.** Three models voting, with confidence scores and disagreement analysis.
3. **Historical baselines.** Every eval run compared against the last 30 runs. You see trends, not just pass/fail.
4. **Trace-level debugging.** See the agent's entire reasoning chain, where it diverged, what context was missing.
5. **Statistical non-determinism handling.** Uses Welch's t-test to determine if a change caused a real regression or just noise.

---

## Chapter 2: The Architecture — A Deep Dive from First Principles

### 2.1 The 30,000-Foot View

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           AgentCI System Architecture                       │
│                                                                             │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │  GitHub   │───▶│  API Gateway │───▶│  Orchestrator│───▶│   Workers    │  │
│  │  Webhook  │    │  (FastAPI)   │    │  (Temporal)  │    │  (Eval Pool) │  │
│  └──────────┘    └──────────────┘    └──────────────┘    └──────────────┘  │
│       │                │                     │                   │          │
│       │                ▼                     ▼                   ▼          │
│       │          ┌──────────┐         ┌──────────────┐   ┌──────────────┐  │
│       │          │  Redis   │         │  PostgreSQL  │   │  Judge LLM   │  │
│       │          │  (Cache) │         │  (State)     │   │  Panel       │  │
│       │          └──────────┘         └──────────────┘   └──────────────┘  │
│       │                                      │                             │
│       │                               ┌──────────────┐                     │
│       └──────────────────────────────▶│  GitHub App  │                     │
│                                       │  (Reporter)  │                     │
│                                       └──────────────┘                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Component-by-Component Breakdown

---

#### Component 1: The GitHub Webhook Receiver

**What it does:** Listens for `pull_request.opened`, `pull_request.synchronize`, and `push` events from GitHub.

**Why it exists:** This is the "trigger." It converts a human action (opening a PR) into a machine workflow (running evaluations).

AgentCI does **intelligent filtering**. Not every PR needs evaluation. If someone changes `README.md`, we don't need to spin up 50 agent simulations. The webhook receiver inspects changed files against a config:

```yaml
# .agentci.yml - lives in the repo root
triggers:
  - pattern: "prompts/**"
    eval_suite: "full"
  - pattern: "src/agents/**"
    eval_suite: "full"
  - pattern: "config/rag_*.yaml"
    eval_suite: "retrieval_only"
  - pattern: "tools/**"
    eval_suite: "tool_use_only"

baselines:
  min_score: 0.95
  comparison: "last_5_runs"
  statistical_test: "welch_t_test"
  significance_level: 0.05
```

**Critical: Webhook Signature Verification**

GitHub signs every webhook payload with HMAC-SHA256. You MUST verify this signature. Without it, anyone can send fake webhooks and trigger arbitrary eval runs (a denial-of-service on your compute budget).

```python
import hmac, hashlib

def verify_github_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

---

#### Component 2: The API Gateway (FastAPI)

**What it does:** The central nervous system. All requests flow through it — authentication, rate limiting, request validation, routing.

**Why FastAPI specifically:**

FastAPI is built on two critical technologies:
1. **Starlette (ASGI)** — Handles requests using Python's `asyncio`, not blocking threads. When 50 eval workers send results simultaneously, FastAPI handles them concurrently on a single thread.
2. **Pydantic** — Automatic request/response validation. Every endpoint has a schema. Malformed data is rejected before your business logic sees it.

**Key Concept: Why Async Matters Here**

```
WSGI (Flask):      Thread 1 ──[Request 1]─────────────────▶ done
                   Thread 2 ──[Request 2]─────────────────▶ done
                   Request 3... WAITING (no threads free)

ASGI (FastAPI):    Event Loop ──[R1]──wait──[R2]──wait──[R3]──wait──[R1]──done
                   (all requests on one thread, switching during I/O)
```

---

#### Component 3: The Orchestrator (Temporal)

**This is the most important architectural decision in the entire system.**

**Why not just use Celery?**

Celery is a task queue. Push a task, a worker executes it, returns a result. But an AgentCI evaluation run is not "a task." It's a **workflow** — a sequence of dependent steps with conditional logic:

```
1. Clone the repo at the PR's commit SHA
2. Build the agent environment (install deps, load configs)
3. Load the evaluation suite (50 test scenarios)
4. For each scenario, IN PARALLEL:
   a. Inject the scenario into the agent
   b. Record the agent's full response + reasoning trace
   c. Send the response to 3 Judge LLMs
   d. Collect all 3 judgments
   e. Compute consensus score
   f. If judges disagree by >20%, trigger a 4th "tiebreaker" judge
5. Aggregate all scenario scores
6. Compare against historical baseline using statistical tests
7. Generate the markdown report
8. Post the report as a GitHub PR comment
9. Set the PR status check to pass/fail
```

If step 4c fails for one scenario (Judge LLM API timeout), Celery retries the **entire task**. Temporal retries **just step 4c**, with exponential backoff, without re-running 4a and 4b.

**Temporal Concepts:**

| Concept | What It Is | AgentCI Example |
|---------|-----------|-----------------|
| **Workflow** | Durable, fault-tolerant function | The entire eval run (steps 1-9) |
| **Activity** | A single side-effect step | "Run scenario #7" or "Call Judge LLM" |
| **Signal** | External event to a running workflow | "User cancelled the PR" → abort all evals |
| **Query** | Read workflow's current state | Dashboard asks "how many scenarios done?" |
| **Child Workflow** | Sub-workflow spawned by parent | Each of the 50 parallel scenario evals |

**The Key Insight: Durable Execution**

If your server crashes mid-evaluation (at scenario 25 of 50), when it restarts, Temporal replays the workflow history and resumes from exactly where it left off. This is **event sourcing** — workflow state derived from a log of events, not a mutable database row.

---

#### Component 4: The Database Layer (PostgreSQL + Redis)

**PostgreSQL — The Source of Truth**

```sql
CREATE TABLE eval_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_full_name  TEXT NOT NULL,
    pr_number       INTEGER NOT NULL,
    commit_sha      TEXT NOT NULL,
    eval_suite      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    baseline_score  FLOAT,
    final_score     FLOAT,
    p_value         FLOAT,            -- statistical significance
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE TABLE scenario_results (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    eval_run_id     UUID REFERENCES eval_runs(id),
    scenario_id     TEXT NOT NULL,
    agent_output    JSONB NOT NULL,
    judge_scores    JSONB NOT NULL,    -- {"judge_1": 0.85, "judge_2": 0.90}
    consensus_score FLOAT NOT NULL,
    judge_reasoning JSONB,
    trace_data      JSONB,            -- full reasoning trace
    passed          BOOLEAN NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE baselines (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_full_name  TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    rolling_mean    FLOAT NOT NULL,
    rolling_stddev  FLOAT NOT NULL,
    sample_count    INTEGER NOT NULL,
    UNIQUE(repo_full_name, scenario_id)
);
```

**Redis — The Speed Layer**
1. **Caching:** Dashboard reads cached eval progress, not PostgreSQL
2. **Pub/Sub:** Real-time updates via WebSocket subscriptions
3. **Rate Limiting:** Prevent abuse and runaway costs per repo

---

### 2.3 Architectural Patterns That Separate Junior from Senior

#### Pattern 1: Event Sourcing

Instead of UPDATE-ing a row when status changes (losing history), store every event:

```
Event 1: EvalRunCreated { run_id: "abc", pr: 42 }
Event 2: ScenarioStarted { run_id: "abc", scenario: "refund" }
Event 3: JudgeScoreReceived { run_id: "abc", judge: 1, score: 0.92 }
Event 4: ScenarioCompleted { run_id: "abc", consensus: 0.90 }
```

Current state = replay all events. This gives you audit trail, time-travel debugging, and rebuild-from-scratch capability.

#### Pattern 2: CQRS (Command Query Responsibility Segregation)

Separate writes from reads:
- **Command (writes):** Insert raw results to PostgreSQL. Optimized for consistency.
- **Query (reads):** Read from denormalized Redis cache. Optimized for speed.

The write pattern ("insert one result") and read pattern ("show all failing scenarios across all runs, sorted by severity") are fundamentally different. Don't optimize one DB for both.

#### Pattern 3: The Saga Pattern

An eval run touches multiple services. What if Judge LLM succeeds but DB write fails?

```
Step 1: Create eval run in DB → Compensate: Mark as "aborted"
Step 2: Build agent sandbox → Compensate: Destroy container
Step 3: Run evaluations → Compensate: Log partial results
Step 4: Post GitHub comment → Compensate: Delete/update comment
```

If any step fails, compensating actions run in reverse. **Eventual consistency** without distributed transactions.

---

### 2.4 The Sandbox Environment

For each eval run, AgentCI:
1. **Builds a Docker image** from the repo's `Dockerfile` or `requirements.txt`
2. **Injects environment variables** from encrypted secrets
3. **Mounts the evaluation harness** as a volume
4. **Sets resource limits** — CPU, memory, timeout per scenario
5. **Intercepts network calls** — custom DNS proxy for logging and cost tracking

---

## Chapter 3: Learning the Stack — The Efficient Path

### 3.1 FastAPI (The API Layer)

**Must-learn concepts:**
- Async/Await in Python (event loop mechanics)
- Dependency Injection (`Depends()` system)
- Pydantic Models (schema validation)
- Middleware (cross-cutting concerns)

**Skip:** Templating (Jinja2), OAuth2 from scratch, WebSocket basics (learn when needed).

**📺 Resources:**
- **"FastAPI Full Course" — Sanjeev Thiyagarajan** (YouTube, ~19 hrs) — Most thorough course. Skip SQL sections if you know SQL.
- **"Async Python Tutorial" — mCoding** (YouTube, ~15 min) — Watch FIRST before touching FastAPI.

### 3.2 Temporal (The Workflow Engine)

**Must-learn concepts:**
- Workflows vs Activities (orchestration vs side-effects)
- Durable Execution (replay-based state recovery)
- Retry Policies (exponential backoff with jitter)
- Task Queues (worker pools per activity type)

**Skip:** Schedules, Nexus, multi-cluster replication.

**📺 Resources:**
- **"Temporal in 7 Minutes" — Temporal** (YouTube) — Perfect mental model.
- **"Building Reliable Distributed Systems with Temporal" — Hussein Nasser** (YouTube, ~40 min) — Deep dive into why it exists.
- **Temporal Python SDK docs** — The official tutorial is excellent.

### 3.3 PostgreSQL (The State Layer)

**Must-learn concepts:**
- JSONB columns (index and query efficiently)
- Window Functions (rolling averages for baselines)
- Indexes (B-tree, GIN for JSONB, partial indexes)
- Connection Pooling (`asyncpg` with pool)

**Skip:** Stored procedures, triggers, replication setup, PL/pgSQL.

**📺 Resources:**
- **"PostgreSQL Tutorial" — Hussein Nasser** (YouTube, ~2 hrs) — Indexing, JSONB, performance.
- **"SQL Window Functions" — Fireship** (YouTube, ~5 min) — Fast visual explanation.

### 3.4 Redis (Cache + Pub/Sub)

**Must-learn concepts:**
- Data structures (Strings, Hashes, Sorted Sets, Pub/Sub)
- TTL (Time-To-Live) for cache expiration
- Pub/Sub for real-time eval progress events

**Skip:** Redis Streams, Cluster, Sentinel, Lua scripting.

**📺 Resources:**
- **"Redis in 100 Seconds" — Fireship** (YouTube) — Best first introduction.
- **"Redis Crash Course" — Traversy Media** (YouTube, ~40 min) — All data structures with examples.

### 3.5 Docker (The Isolation Layer)

**Must-learn concepts:**
- Multi-stage builds
- Volume mounts (injecting eval harness)
- Resource limits (`--memory`, `--cpus`, `--pids-limit`)
- Docker SDK for Python (programmatic container management)

**📺 Resources:**
- **"Docker in 100 Seconds" — Fireship** (YouTube) — Mental model.
- **"Docker Crash Course" — TechWorld with Nana** (YouTube, ~1 hr) — Most beginner-friendly.
- **"Docker Networking" — NetworkChuck** (YouTube, ~20 min) — How containers communicate.

---

*End of Part 1. Part 2 covers: The Evaluation Engine deep-dive, LLM-as-a-Judge theory, Statistical Testing, and the complete step-by-step implementation procedure.*
