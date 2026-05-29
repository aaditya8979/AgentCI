# Contributing to AgentCI

Thank you for your interest in contributing to AgentCI! This document provides guidelines and instructions for contributing.

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Running Tests](#running-tests)
- [Code Style](#code-style)
- [Submitting Changes](#submitting-changes)
- [Issue Guidelines](#issue-guidelines)

---

## Code of Conduct

Be respectful. Be constructive. We're all here to build great software.

---

## Development Setup

### Prerequisites

- Python 3.11+
- Node.js 18+ (for the dashboard)
- Docker & Docker Compose (for integration tests)

### 1. Clone and install

```bash
git clone https://github.com/aaditya8979/AgentCI.git
cd AgentCI

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# or: .venv\Scripts\activate  # Windows

# Install with all dev dependencies
pip install -e ".[all]"
```

### 2. Verify installation

```bash
# Run the test suite
pytest tests/ -v

# Check the CLI works
agentci --help

# Lint
ruff check src/ tests/
```

### 3. Dashboard development (optional)

```bash
cd dashboard
npm install
npm run dev
# Opens at http://localhost:3000
```

---

## Project Structure

```
src/agentci/
├── api/              # FastAPI server
│   ├── main.py       # App lifecycle, middleware
│   ├── webhook.py    # GitHub webhook handler
│   ├── routes.py     # REST API endpoints
│   └── ws.py         # WebSocket for live progress
├── judge/            # LLM-as-a-Judge engine
│   ├── llm_judge.py  # Single judge
│   ├── consensus.py  # Multi-judge consensus
│   └── async_consensus.py  # Parallel + tiered evaluation
├── workflows/        # Temporal orchestration
│   ├── eval_workflow.py   # Workflow definitions
│   ├── activities.py      # Activity implementations
│   └── worker.py          # Worker process
├── db/               # PostgreSQL layer
├── stats/            # Statistical analysis
├── reporter/         # GitHub + console output
├── cache/            # Redis + semantic caching
├── runner/           # Agent execution sandbox
├── models/           # Pydantic data models
└── cli.py            # Click CLI
```

---

## Running Tests

```bash
# Run all unit tests (fast, no infrastructure needed)
pytest tests/ -v

# Run with coverage report
pytest tests/ --cov=agentci --cov-report=html
open htmlcov/index.html

# Run integration tests (requires Docker services)
AGENTCI_INTEGRATION_TESTS=1 pytest tests/integration/ -v

# Run a specific test file
pytest tests/test_pricing.py -v

# Run a specific test
pytest tests/test_webhook.py::TestSignatureVerification::test_valid_signature -v
```

### Test conventions

- **Unit tests** live in `tests/` — they mock all external services and run instantly.
- **Integration tests** live in `tests/integration/` — they require PostgreSQL, Redis, and Temporal. Gated behind `AGENTCI_INTEGRATION_TESTS=1`.
- Every implementation change must keep all existing tests passing.
- New features should include tests.

---

## Code Style

We use [Ruff](https://github.com/astral-sh/ruff) for linting and formatting.

```bash
# Check for issues
ruff check src/ tests/

# Auto-fix what's possible
ruff check --fix src/ tests/
```

### Key conventions

- **Line length:** 120 characters
- **Imports:** Use `from __future__ import annotations` in all files
- **Type hints:** Use modern syntax (`str | None` not `Optional[str]`)
- **Docstrings:** Required for all public functions and classes
- **Logging:** Use `logging.getLogger(__name__)` — never `print()`
- **Database:** All SQL queries go in `db/queries.py` — no raw SQL elsewhere
- **Async:** All I/O operations must be async

---

## Submitting Changes

### 1. Create a branch

```bash
git checkout -b feat/your-feature-name
# or: git checkout -b fix/your-bug-fix
```

### 2. Make your changes

- Write tests for new functionality
- Update docstrings if interfaces change
- Keep commits focused and well-described

### 3. Verify

```bash
# All tests must pass
pytest tests/ -v

# No lint issues
ruff check src/ tests/
```

### 4. Submit a PR

- Title: Use conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`)
- Description: Explain **what** changed and **why**
- Link any related issues

---

## Issue Guidelines

### Bug reports

Include:
- Python version and OS
- Steps to reproduce
- Expected vs actual behavior
- Error traceback (if applicable)

### Feature requests

Include:
- Use case description
- Proposed API/interface
- Any alternatives you've considered

---

## Architecture Decisions

If you're making significant changes, here are key design principles:

1. **Singleton DB pool** — `connection.py` manages a process-wide pool. Use `get_pool()` to access it. Never create pools elsewhere.
2. **Temporal for orchestration** — All long-running work goes through Temporal workflows. Activities are individually retryable.
3. **Cross-family judges** — The consensus panel must use judges from different LLM families to prevent self-enhancement bias.
4. **Statistical rigor** — Regression detection uses Welch's t-test (not paired t-test) because run-to-run samples are independent.
5. **Graceful degradation** — Redis and Temporal being down should not crash the API. Log warnings and continue.

---

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
