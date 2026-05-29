# Quick Start

Get AgentCI running in 5 minutes.

## 1. Create Your Agent

AgentCI evaluates any Python function that takes input and returns output:

```python
# agent.py
def run(input_data: dict) -> dict:
    """Your LLM agent — this is what AgentCI evaluates."""
    messages = input_data.get("messages", [])
    last_message = messages[-1]["content"] if messages else ""
    
    # Your agent logic here (OpenAI, LangChain, etc.)
    return {"response": "Your agent's response"}
```

## 2. Write Evaluation Scenarios

Scenarios define what to test and how to grade:

```json
[
  {
    "scenario_id": "greeting",
    "description": "Basic greeting — agent should respond helpfully",
    "category": "accuracy",
    "difficulty": "easy",
    "conversation": [
      {"role": "user", "content": "Hello, I need help with my order."}
    ],
    "rubric": {
      "criteria": [
        {"name": "accuracy", "weight": 0.3, "description": "Response is relevant and correct"},
        {"name": "tone", "weight": 0.3, "description": "Professional and empathetic"},
        {"name": "no_hallucination", "weight": 0.4, "description": "No fabricated information"}
      ],
      "passing_threshold": 0.85
    }
  }
]
```

Save this as `eval/scenarios.json`.

## 3. Run Your First Evaluation

```bash
agentci eval \
  --agent agent.py \
  --scenarios eval/scenarios.json \
  --format rich
```

## 4. Review the Results

AgentCI prints a detailed report showing:

- Per-scenario scores with criterion breakdown
- Baseline comparison (after 3+ runs)
- Statistical significance of any regressions
- Pass/fail status based on your threshold

## 5. Add to CI (Optional)

Create `.agentci.yml` in your repo root:

```yaml
version: "1"
agent_entry: agent.py
agent_function: run
scenarios_path: eval/scenarios.json

judges:
  models: [gpt-4o, claude-sonnet-4-20250514, gemini-2.5-pro]
  ija_threshold: 0.7

baselines:
  min_score: 0.85
  comparison: last_5_runs
  statistical_test: welch_t_test
```

Install the [AgentCI GitHub App](https://github.com/apps/agent-ci-aaditya) to get automatic evaluations on every PR.

## Next Steps

- [Configuration Reference →](configuration.md)
- [Architecture Overview →](../architecture/overview.md)
- [Self-Hosting →](../self-hosting/docker.md)
