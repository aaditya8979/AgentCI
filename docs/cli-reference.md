# CLI Reference

## `agentci eval`

Run evaluation against scenarios.

```bash
agentci eval [OPTIONS]
```

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--agent` | `-a` | `.agentci.yml` | Path to agent module |
| `--scenarios` | `-s` | `.agentci.yml` | Path to scenarios JSON |
| `--format` | `-f` | `rich` | Output format: `rich`, `json`, `markdown` |
| `--output` | `-o` | stdout | Write results to file |
| `--verbose` | `-v` | false | Show per-judge scores |
| `--config` | `-c` | `.agentci.yml` | Config file path |

### Examples

```bash
# Basic evaluation with rich output
agentci eval -a agent.py -s eval/scenarios.json

# JSON output for CI pipelines
agentci eval -a agent.py -s eval/scenarios.json -f json -o results.json

# Verbose mode (shows individual judge scores)
agentci eval -a agent.py -s eval/scenarios.json -v
```

---

## `agentci generate`

Generate evaluation scenarios from system prompts.

```bash
agentci generate [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--prompt` | required | Path to system prompt file |
| `--domain` | auto-detect | Domain: `customer_support`, `coding`, `fintech`, etc. |
| `--count` | 5 | Number of scenarios to generate |
| `--output` | stdout | Output file path |

### Examples

```bash
agentci generate --prompt prompts/system.txt --count 10 -o eval/scenarios.json
```

---

## `agentci compare`

Compare two evaluation runs for regression detection.

```bash
agentci compare BASELINE_FILE CURRENT_FILE
```

---

## `agentci init`

Initialize AgentCI in your project.

```bash
agentci init [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--github-actions` | Generate a GitHub Actions workflow |

---

## `agentci status`

Check system status and connectivity.

```bash
agentci status
```
