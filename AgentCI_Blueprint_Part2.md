# AgentCI Blueprint — PART 2

## THE EVALUATION ENGINE, LLM-AS-A-JUDGE, AND STATISTICAL TESTING

---

# Chapter 4: The Evaluation Engine — The Brain of AgentCI

> This is the core IP of AgentCI. Everything else is plumbing. This chapter is where you go from "I can build web apps" to "I understand AI infrastructure."

---

## 4.1 What Is an "Eval" — Really?

An eval is a **structured test** that answers one question: *"Did the agent do the right thing?"*

But unlike traditional tests, there's no `assertEqual`. Instead, you define:

1. **A Scenario** — A simulated input (a user message, a multi-turn conversation, a document to summarize)
2. **A Rubric** — The criteria for "correct" (did it issue the refund? did it stay on topic? did it cite sources?)
3. **A Judge** — Something that reads the agent's output and scores it against the rubric

The key insight: **the judge is itself an LLM.** This is LLM-as-a-Judge.

---

## 4.2 Anatomy of a Test Scenario

```json
{
  "scenario_id": "angry_customer_refund_001",
  "description": "Customer is angry about a defective product, demands full refund",
  "category": "refund_handling",
  "difficulty": "medium",
  "conversation": [
    {
      "role": "user",
      "content": "I bought your Premium Widget 3 weeks ago and it broke on day 2. This is UNACCEPTABLE. I want a full refund RIGHT NOW or I'm filing a chargeback."
    }
  ],
  "rubric": {
    "criteria": [
      {
        "name": "refund_policy_compliance",
        "description": "Agent correctly identifies that the product is within the 30-day return window and initiates a refund process",
        "weight": 0.3
      },
      {
        "name": "empathy_and_tone",
        "description": "Agent acknowledges the customer's frustration without being dismissive or overly apologetic",
        "weight": 0.2
      },
      {
        "name": "no_hallucination",
        "description": "Agent does not invent policies, promises, or information that doesn't exist in its knowledge base",
        "weight": 0.3
      },
      {
        "name": "action_taken",
        "description": "Agent either issues the refund or escalates to a human, does not leave the customer in limbo",
        "weight": 0.2
      }
    ],
    "passing_threshold": 0.85
  },
  "context": {
    "product_database": "Premium Widget - $49.99 - 30-day return policy",
    "customer_history": "First purchase, no prior complaints"
  }
}
```

**Why this structure matters:**

- **Weighted criteria** let you express that "not hallucinating" is more important than "being empathetic"
- **Context injection** simulates real RAG by giving the agent access to specific knowledge
- **Categories** let you run partial eval suites (only `refund_handling` scenarios when RAG config changes)

---

## 4.3 LLM-as-a-Judge — The Deep Theory

### 4.3.1 Why Use an LLM as a Judge?

Traditional software tests use **exact match** or **regex** to verify outputs. This fails for LLMs because:
- "I'll process your refund immediately" and "Let me initiate that refund for you right away" are semantically identical but string-different
- You'd need to write hundreds of regex patterns per scenario
- The patterns become stale as the agent's language evolves

An LLM judge understands **semantic equivalence**. You give it the rubric and the output, and it determines whether the output satisfies the criteria — regardless of exact wording.

### 4.3.2 The Judge Prompt Architecture

The judge prompt is the most critical piece of engineering in the entire system. A bad judge prompt produces unreliable scores, which makes the entire platform useless.

**The Three-Part Judge Prompt:**

```
PART 1: ROLE AND CALIBRATION
"You are an expert quality evaluator for AI customer support agents.
You will be given a customer scenario, the agent's response, and a
scoring rubric. Your job is to score the response on each criterion
from 0.0 to 1.0.

CALIBRATION EXAMPLES:
- Score 1.0: The response perfectly satisfies the criterion
- Score 0.8: The response mostly satisfies with minor gaps
- Score 0.5: The response partially satisfies with notable issues
- Score 0.2: The response barely addresses the criterion
- Score 0.0: The response completely fails the criterion"

PART 2: THE EVALUATION CONTEXT
"SCENARIO: {scenario_description}
CUSTOMER MESSAGE: {customer_input}
AGENT RESPONSE: {agent_output}
AVAILABLE CONTEXT: {rag_context}"

PART 3: THE RUBRIC AND OUTPUT FORMAT
"CRITERIA TO EVALUATE:
1. {criterion_1_name}: {criterion_1_description}
2. {criterion_2_name}: {criterion_2_description}
...

Respond ONLY in this JSON format:
{
  "scores": {
    "criterion_1": { "score": 0.0-1.0, "reasoning": "..." },
    "criterion_2": { "score": 0.0-1.0, "reasoning": "..." }
  },
  "overall_assessment": "...",
  "confidence": 0.0-1.0
}"
```

**Why calibration examples matter:**

Without calibration, different judge models interpret the scale differently. GPT-4 tends to be generous (0.85+ for mediocre responses). Claude tends to be stricter. Calibration examples anchor both models to the same scale.

### 4.3.3 The Consensus Panel — Why Three Judges

A single judge has failure modes:
- **Position bias:** LLMs rate the first option higher in A/B comparisons
- **Verbosity bias:** Longer responses get higher scores regardless of quality
- **Self-enhancement bias:** An LLM judges its own model family's outputs more favorably

**Solution: A panel of 3 judges with consensus voting.**

```
Judge Panel Configuration:
├── Judge 1: GPT-4o (strong reasoning, tends generous)
├── Judge 2: Claude 3.5 Sonnet (precise, tends strict)
└── Judge 3: Gemini 1.5 Pro (balanced, good at structured eval)

Consensus Algorithm:
1. All 3 judges score independently
2. Compute median score (not mean — resistant to outliers)
3. Compute Inter-Judge Agreement (IJA):
   IJA = 1 - (max_score - min_score)
4. If IJA < 0.7 (judges disagree by >30%):
   a. Trigger a 4th "tiebreaker" judge with the other judges' reasoning
   b. The tiebreaker sees: "Judge 1 scored 0.9 because X. Judge 2
      scored 0.4 because Y. Please evaluate independently."
5. Final consensus = weighted median of all judges
```

**Why median, not mean?**

If Judge 1 scores 0.90, Judge 2 scores 0.85, and Judge 3 scores 0.20 (hallucinated or had an API error), the mean is 0.65 (unfairly low). The median is 0.85 (correctly ignores the outlier).

### 4.3.4 Cost Optimization for the Judge Panel

Running 3 frontier models × 50 scenarios × every PR = expensive. Here's how to manage costs:

**Tiered Evaluation:**
```
Tier 1 (Fast, Cheap): Use GPT-4o-mini as a single "screening" judge
  - If score > 0.95: AUTO-PASS (skip full panel)
  - If score < 0.30: AUTO-FAIL (skip full panel)
  - If 0.30 ≤ score ≤ 0.95: Escalate to Tier 2

Tier 2 (Full Panel): Run all 3 frontier judges
  - Only ~30-40% of scenarios reach this tier
  - Total cost reduction: 50-60%
```

**Caching:** If the same scenario produces the exact same agent output as a previous run (happens with temperature=0), reuse the previous judgment instead of calling the judge API again.

---

## 4.4 Statistical Testing — Handling Non-Determinism Mathematically

This is what separates a toy project from a production system.

### 4.4.1 The Problem

You run the same eval suite twice with zero code changes. Run 1 scores 0.92. Run 2 scores 0.89. Is this a regression? No — it's just noise from LLM non-determinism (both the agent and the judges introduce variance).

If you report every score fluctuation as a regression, developers will start ignoring your reports. **False positives destroy trust.**

### 4.4.2 The Solution: Welch's t-test

Welch's t-test determines whether two sets of scores come from populations with different means, even when the sets have different variances and sample sizes.

**How it works in AgentCI:**

```
Baseline: Last 5 eval runs for this scenario
  scores = [0.92, 0.89, 0.91, 0.90, 0.93]
  mean = 0.91, std = 0.015

Current Run: This PR's eval
  scores = [0.85, 0.82, 0.84, 0.83, 0.86]  (run 5 times for stability)
  mean = 0.84, std = 0.015

Welch's t-test:
  t = (0.91 - 0.84) / sqrt(0.015²/5 + 0.015²/5)
  t = 0.07 / 0.0095 = 7.37
  p-value ≈ 0.0001

Since p < 0.05 → This is a STATISTICALLY SIGNIFICANT regression.
Report it. Block the PR.
```

**The implementation:**

```python
from scipy import stats

def is_regression(baseline_scores: list[float],
                  current_scores: list[float],
                  significance: float = 0.05) -> tuple[bool, float]:
    """
    Returns (is_regression, p_value).
    Uses one-sided Welch's t-test (we only care if current < baseline).
    """
    t_stat, p_value = stats.ttest_ind(
        baseline_scores, current_scores,
        equal_var=False,       # Welch's (don't assume equal variance)
        alternative='greater'  # One-sided: baseline > current?
    )
    return p_value < significance, p_value
```

### 4.4.3 Why Not Just Use Mean Comparison?

```
Scenario A: Baseline mean = 0.90, Current mean = 0.87
  Baseline std = 0.01 (very consistent)
  → p = 0.001 → REAL REGRESSION (the agent is consistently worse)

Scenario B: Baseline mean = 0.90, Current mean = 0.87
  Baseline std = 0.08 (very noisy)
  → p = 0.42 → NOT SIGNIFICANT (the difference is within normal noise)
```

Both have the same mean delta (-0.03), but only Scenario A is a real problem. Statistical testing accounts for variance. Mean comparison doesn't.

### 4.4.4 Effect Size — How Bad Is the Regression?

p-value tells you IF there's a regression. Cohen's d tells you HOW BIG it is.

```python
def cohens_d(baseline: list[float], current: list[float]) -> float:
    pooled_std = ((len(baseline)-1)*np.std(baseline)**2 +
                  (len(current)-1)*np.std(current)**2) / \
                 (len(baseline) + len(current) - 2)
    pooled_std = np.sqrt(pooled_std)
    return (np.mean(baseline) - np.mean(current)) / pooled_std

# Interpretation:
# d < 0.2  → Negligible (warn, don't block)
# d 0.2-0.5 → Small (block, but with low severity)
# d 0.5-0.8 → Medium (block, flag for review)
# d > 0.8  → Large (block, alert team lead)
```

---

## 4.5 The Trace System — Debugging Agent Failures

When a scenario fails, the developer needs to understand WHY. "Score: 0.42" is useless without context.

**What AgentCI captures for every scenario:**

```json
{
  "trace": {
    "agent_reasoning": [
      { "step": 1, "type": "system_prompt_loaded", "content": "You are a helpful..." },
      { "step": 2, "type": "user_message_received", "content": "I want a refund..." },
      { "step": 3, "type": "rag_retrieval", "query": "refund policy widget",
        "results": ["30-day return policy...", "Premium Widget specs..."],
        "latency_ms": 145 },
      { "step": 4, "type": "tool_call", "tool": "check_order_status",
        "input": { "customer_id": "sim_001" },
        "output": { "order_date": "2024-01-15", "status": "delivered" } },
      { "step": 5, "type": "llm_generation", "model": "gpt-4o",
        "prompt_tokens": 1847, "completion_tokens": 312,
        "temperature": 0.3, "content": "I understand your frustration..." }
    ],
    "total_latency_ms": 2340,
    "total_cost_usd": 0.0087
  }
}
```

This trace lets developers see:
- Did the RAG retrieve relevant context? (step 3)
- Did the agent call the right tools? (step 4)
- Where in the reasoning chain did it go wrong?
- How much did this single scenario cost?

---

# Chapter 5: The GitHub Integration — Making It Developer-Native

## 5.1 The GitHub App

AgentCI is a **GitHub App**, not a GitHub Action. The difference matters:

| Feature | GitHub Action | GitHub App |
|---------|--------------|-----------|
| Runs on | GitHub's runners (limited) | Your own infrastructure |
| Timeout | 6 hours max | Unlimited |
| State | Stateless (no persistence between runs) | Stateful (your own database) |
| Secrets | Stored in GitHub | Stored in your vault |
| UI | Log output only | Custom check runs with rich markdown |

A GitHub App can:
- Create **Check Runs** with detailed markdown output, inline annotations, and status indicators
- Post **PR comments** with formatted eval reports
- Set **commit statuses** (pending/success/failure) that block merging
- React to **webhooks** in real-time

## 5.2 The PR Report — What Developers Actually See

When AgentCI completes an evaluation, it posts a comment like this:

```markdown
## 🔍 AgentCI Eval Report — PR #42

**Commit:** `a1b2c3d` | **Suite:** `full` | **Duration:** 2m 34s

### 📊 Overall: ✅ PASSED (0.93 vs baseline 0.91, p=0.34)

| Scenario | Score | Baseline | Delta | Status |
|----------|-------|----------|-------|--------|
| angry_customer_refund | 0.95 | 0.92 | +0.03 | ✅ |
| out_of_stock_inquiry | 0.91 | 0.89 | +0.02 | ✅ |
| billing_dispute | 0.88 | 0.90 | -0.02 | ✅ (p=0.31) |
| legal_compliance_check | 0.42 | 0.94 | -0.52 | ❌ (p<0.001) |

### ❌ Failed Scenarios

<details>
<summary><b>legal_compliance_check</b> — Score: 0.42 (baseline: 0.94)</summary>

**Judge Consensus:** 3/3 judges agree this is a failure

**What went wrong:** The agent incorrectly stated that the company
offers a "lifetime warranty" on all products. This policy does not
exist in the knowledge base. This is a hallucination.

**Regression cause:** The new system prompt removed the instruction
"Only cite policies that exist in the provided context."

**Trace:** [View full reasoning trace →](https://agentci.dev/trace/abc123)
</details>

---
*Powered by AgentCI v0.1.0 | [Dashboard](https://agentci.dev) | [Docs](https://docs.agentci.dev)*
```

---

# Chapter 6: The Complete Implementation Procedure

## Phase 1: The CLI Foundation (Week 1-2)

**Goal:** A working Python CLI that takes an agent script + test cases, runs them, and prints results.

### Step 1: Project Structure
```
agentci/
├── pyproject.toml
├── src/
│   └── agentci/
│       ├── __init__.py
│       ├── cli.py              # Click-based CLI
│       ├── config.py           # .agentci.yml parser
│       ├── runner/
│       │   ├── __init__.py
│       │   ├── agent_runner.py # Executes the agent with scenarios
│       │   └── sandbox.py      # Docker-based isolation
│       ├── judge/
│       │   ├── __init__.py
│       │   ├── base.py         # Abstract judge interface
│       │   ├── llm_judge.py    # LLM-as-a-Judge implementation
│       │   ├── consensus.py    # Multi-judge consensus logic
│       │   └── prompts.py      # Judge prompt templates
│       ├── stats/
│       │   ├── __init__.py
│       │   ├── baseline.py     # Rolling baseline computation
│       │   └── significance.py # Welch's t-test, Cohen's d
│       ├── reporter/
│       │   ├── __init__.py
│       │   ├── console.py      # Terminal output (rich tables)
│       │   ├── markdown.py     # GitHub PR comment generator
│       │   └── github.py       # GitHub API client
│       └── models/
│           ├── __init__.py
│           ├── scenario.py     # Pydantic models for test scenarios
│           ├── result.py       # Eval result models
│           └── config.py       # Config models
├── tests/
│   ├── test_judge.py
│   ├── test_consensus.py
│   ├── test_stats.py
│   └── fixtures/
│       └── sample_scenarios.json
└── examples/
    ├── simple_agent.py
    └── test_scenarios.json
```

### Step 2: Core Models (Day 1)
Define Pydantic models for scenarios, results, and config.

### Step 3: Agent Runner (Day 2-3)
Build the module that loads the agent script, injects scenarios, and captures outputs with full traces.

### Step 4: Judge System (Day 4-7)
Implement the LLM-as-a-Judge with multi-model consensus panel.

### Step 5: Statistical Testing (Day 8-9)
Implement Welch's t-test, Cohen's d, and baseline tracking.

### Step 6: CLI Interface (Day 10)
Wire everything together with Click:
```bash
agentci eval --agent ./my_agent.py --scenarios ./tests.json --judges 3
```

## Phase 2: The GitHub Integration (Week 3-4)

### Step 1: GitHub App Registration
Register a GitHub App with permissions: `checks:write`, `pull_requests:write`, `contents:read`.

### Step 2: Webhook Server
FastAPI server that receives GitHub webhooks, verifies signatures, and triggers eval workflows.

### Step 3: PR Reporter
Generate markdown reports and post them as PR comments using the GitHub API.

### Step 4: Status Checks
Set commit status to `pending` when eval starts, `success`/`failure` when it completes.

## Phase 3: The Orchestration Layer (Week 5-6)

### Step 1: Temporal Setup
Deploy Temporal server (Docker Compose for dev, Temporal Cloud for prod).

### Step 2: Workflow Definition
Define the evaluation workflow with parallel scenario execution and failure handling.

### Step 3: Worker Pool
Build workers that execute agent scenarios in Docker sandboxes.

## Phase 4: The Dashboard (Week 7-8)

### Step 1: Next.js Setup
Create a Next.js app with the dashboard layout.

### Step 2: Core Pages
- **Eval History:** Timeline of all eval runs per repo
- **Run Detail:** Scenario-by-scenario breakdown with traces
- **Baseline Trends:** Charts showing score evolution over time
- **Config Editor:** Visual editor for `.agentci.yml`

### Step 3: Real-time Updates
WebSocket connection to Redis Pub/Sub for live eval progress.

---

# Chapter 7: Advanced Concepts & Resources

## 7.1 OpenTelemetry for Agent Tracing

OpenTelemetry (OTel) is the industry standard for distributed tracing. AgentCI uses it to capture agent behavior:

```python
from opentelemetry import trace

tracer = trace.get_tracer("agentci.eval")

async def run_scenario(agent, scenario):
    with tracer.start_as_current_span("scenario_eval") as span:
        span.set_attribute("scenario.id", scenario.id)
        span.set_attribute("scenario.category", scenario.category)

        with tracer.start_as_current_span("agent_execution"):
            output = await agent.run(scenario.input)

        with tracer.start_as_current_span("judge_evaluation"):
            scores = await judge_panel.evaluate(output, scenario.rubric)

        span.set_attribute("result.score", scores.consensus)
        span.set_attribute("result.passed", scores.passed)
```

**📺 Resources:**
- **"OpenTelemetry in 100 Seconds" — Fireship** (YouTube) — Quick mental model
- **"Distributed Tracing with OpenTelemetry" — IBM Technology** (YouTube, ~10 min) — Why tracing matters

## 7.2 The GitHub Actions Wrapper

Even though AgentCI runs on your infrastructure, you provide a thin GitHub Action wrapper for easy setup:

```yaml
# .github/workflows/agentci.yml
name: AgentCI Evaluation
on:
  pull_request:
    paths:
      - 'prompts/**'
      - 'src/agents/**'

jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: agentci/action@v1
        with:
          api-key: ${{ secrets.AGENTCI_API_KEY }}
          eval-suite: full
          baseline-comparison: last_5
```

## 7.3 Essential YouTube Learning Path (Concise & Ordered)

**Watch in this order. Total ~8 hours to get the full picture:**

### Foundation (2 hours)
1. 📺 **"How To Build AI Agents" — AI Jason** (~20 min) — Understand what AI agents are
2. 📺 **"Async Python Tutorial" — mCoding** (~15 min) — asyncio fundamentals
3. 📺 **"Docker in 100 Seconds + Crash Course" — Fireship + TechWorld with Nana** (~1.5 hrs)

### Backend Architecture (3 hours)
4. 📺 **"Temporal in 7 Minutes" — Temporal** — Workflow engine mental model
5. 📺 **"Event Driven Architecture" — Hussein Nasser** (~30 min) — Event sourcing, CQRS
6. 📺 **"System Design for Beginners" — Gaurav Sen** (~30 min) — How to think about scale
7. 📺 **"Redis Crash Course" — Traversy Media** (~40 min) — Caching + Pub/Sub
8. 📺 **"PostgreSQL Tutorial" — Hussein Nasser** (~2 hrs, watch at 1.5x)

### AI/Eval Specific (2 hours)
9. 📺 **"LLM Evaluation & Testing" — AI Engineer Conference talks** — Search for recent conf talks
10. 📺 **"Building LLM Judges" — Anthropic/OpenAI blog posts** — Read these, they're better than video
11. 📺 **"Statistical Testing for Data Science" — StatQuest with Josh Starmer** (~20 min) — t-tests explained visually

### Frontend (1 hour)
12. 📺 **"Next.js in 100 Seconds + Full Tutorial" — Fireship** (~1 hr) — Dashboard framework

## 7.4 Key Blog Posts & Papers to Read

1. **"Judging LLM-as-a-Judge" (Zheng et al., 2023)** — The foundational paper on using LLMs as evaluators. Read the methodology section carefully.
2. **"G-Eval: NLG Evaluation using GPT-4" (Liu et al., 2023)** — How to use chain-of-thought in judge prompts for more reliable scoring.
3. **Anthropic's "Evaluating AI Systems" blog** — Practical guide from the Claude team.
4. **"Temporal: Durable Execution" docs** — Better than any video. Read the "Why Temporal" page.
5. **GitHub Apps documentation** — The official guide for building GitHub integrations.

---

# Chapter 8: What Makes This Resume-Worthy

## 8.1 The Skills Matrix

| Skill | Where You Learn It in AgentCI |
|-------|------------------------------|
| Distributed Systems | Temporal workflows, worker pools, saga patterns |
| Statistical Analysis | Welch's t-test, Cohen's d, significance testing |
| LLM Engineering | Judge prompt design, consensus algorithms, cost optimization |
| DevOps/CI-CD | GitHub Apps, webhook processing, Docker sandboxing |
| Database Design | PostgreSQL schema, JSONB indexing, window functions |
| Real-time Systems | Redis Pub/Sub, WebSocket live updates |
| API Design | FastAPI, Pydantic schemas, async handlers |
| Frontend | Next.js dashboard, data visualization, real-time UI |
| Security | HMAC verification, secret management, container isolation |
| Observability | OpenTelemetry tracing, structured logging |

## 8.2 How to Talk About It in Interviews

> "I built AgentCI, a CI/CD quality gate for AI agents. It intercepts PRs that modify agent configurations, spins up sandboxed evaluations using Docker, runs scenarios through a multi-model judge panel with consensus voting, and uses Welch's t-test to determine if score changes are statistically significant regressions or just LLM noise. It blocks the PR and posts a detailed failure report with full reasoning traces directly on GitHub."

Every phrase in that sentence maps to a real, deep technical concept. No fluff.

---

*End of AgentCI Blueprint. You now have everything you need to build a production-grade AI evaluation CI/CD platform.*
