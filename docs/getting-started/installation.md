# Installation

## Requirements

- Python 3.11 or higher
- At least one LLM API key (OpenAI, Anthropic, or Google)

## Install from PyPI

```bash
pip install agentci
```

## Install from Source

```bash
git clone https://github.com/aaditya8979/AgentCI.git
cd AgentCI
pip install -e ".[dev]"
```

## Verify Installation

```bash
agentci --help
```

You should see:

```
Usage: agentci [OPTIONS] COMMAND [ARGS]...

  AgentCI — CI/CD Quality Gate for LLM Agents.

Options:
  --version  Show version and exit.
  --help     Show this message and exit.

Commands:
  eval      Run evaluation against scenarios.
  generate  Generate scenarios from system prompts.
  init      Initialize AgentCI in your project.
  status    Check system status.
```

## Set Up LLM API Keys

AgentCI needs access to LLM APIs for the judge panel. Set at least one:

```bash
export OPENAI_API_KEY=sk-...
# and/or
export ANTHROPIC_API_KEY=sk-ant-...
# and/or
export GOOGLE_API_KEY=AIza...
```

## Next Steps

- [Quick Start →](quickstart.md)
