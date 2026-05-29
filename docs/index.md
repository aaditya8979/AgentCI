# AgentCI

**CI/CD Quality Gate for LLM Agents**

Catch regressions, hallucinations, and safety violations before they reach production.

---

## What is AgentCI?

AgentCI is a continuous integration framework designed specifically for LLM-powered agents. It acts as an automated quality gate in your CI/CD pipeline, running **multi-judge consensus panels** against your agent's behavior to catch problems *before* they reach production.

### The Problem

You changed a system prompt. You swapped a model. You updated a RAG pipeline. **Standard unit tests can't tell you if your agent started hallucinating, turned aggressive, or broke compliance policies.**

### The Solution

AgentCI runs your agent against evaluation scenarios, judges the outputs using a panel of 3 LLMs from different families, and uses **statistical regression detection** (Welch's t-test + Cohen's d) to determine if behavior actually degraded — not just "the score went down," but "it went down with p=0.003."

## Key Features

- ⚖️ **Multi-Judge Consensus** — 3 judges, median aggregation, tiebreaker on disagreement
- 📉 **Statistical Regression Detection** — Welch's t-test + Cohen's d effect sizes
- 🔄 **Two-Tier Evaluation** — Cheap screening + full panel escalation for cost reduction
- 🧠 **Semantic Output Caching** — Cosine-similarity matching to reuse scores
- 📡 **Real-Time Dashboard** — WebSocket-powered live progress
- 🔗 **GitHub App** — Automatic evaluations on every pull request

## Quick Links

- [Installation](getting-started/installation.md)
- [Quick Start](getting-started/quickstart.md)
- [Architecture Overview](architecture/overview.md)
- [Self-Hosting](self-hosting/docker.md)
- [GitHub App](https://github.com/apps/agent-ci-aaditya)
- [Source Code](https://github.com/aaditya8979/AgentCI)
