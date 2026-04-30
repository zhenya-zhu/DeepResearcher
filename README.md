# Deep Researcher

A debuggable, model-agnostic deep research workflow. Given a research question, it plans an investigation, iteratively searches and gathers evidence, then produces a structured long-form report with cited sources.

## Features

- **Multi-model**: routes to Claude, GPT-5, Gemini, Sonar via a unified LiteLLM/OpenAI-compatible gateway
- **Two modes**: `breadth` (survey-style) and `depth` (deep reasoning with iterative verification)
- **Observable**: every run produces `events.jsonl`, `trace.html`, prompt/response artifacts
- **Resumable**: checkpoint/resume for long-running research sessions
- **Local-first evidence**: ingest PDFs, markdown, CSV from workspace directories as first-party sources
- **Semantic evidence engine**: JSON-driven evidence profiles and source packs, no hardcoded domain logic

## Quick Start

```bash
uv venv .venv && uv sync
```

Set required environment variables:

```bash
export DEEP_RESEARCHER_API_KEY="your-api-key"
export DEEP_RESEARCHER_BASE_URL="http://localhost:6655/litellm/v1"
```

Run a research query:

```bash
uv run python -m deep_researcher "评估 2026 年企业级 AI Agent 平台格局"
```

## Usage

```bash
# From a question file (numbered list or JSON)
uv run python -m deep_researcher --question-file queries.json --query-index 1

# Plan only (no research execution)
uv run python -m deep_researcher --plan-only "your question"

# Deep reasoning mode
uv run python -m deep_researcher --mode depth "your question"

# Resume from checkpoint
uv run python -m deep_researcher --resume runs/<run_id>/checkpoints/final.json

# With local documents as evidence
uv run python -m deep_researcher --workspace-source ./my-docs "your question"

# Override models per role
uv run python -m deep_researcher \
  --planner-models anthropic--claude-4.6-sonnet \
  --writer-models gpt-5 \
  "your question"
```

### Testing & Development

```bash
# Mock LLM + tools (offline, fast iteration)
uv run python -m deep_researcher --mock "your question"

# Real LLM, mock tools (test prompt quality without network)
uv run python -m deep_researcher --mock-tools "your question"

# Run tests
uv run python -m unittest discover -s tests
```

## Output

Each run creates `runs/<run_id>/`:

```
runs/<run_id>/
├── report.md              # Final report
├── plan.md / plan.json    # Research plan
├── events.jsonl           # Structured event stream
├── trace.html             # Visual timeline
├── checkpoints/           # Resumable snapshots
├── artifacts/             # Prompt/response logs
└── sources/               # Fetched evidence
```

## Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `DEEP_RESEARCHER_API_KEY` | API key for LLM gateway | (required) |
| `DEEP_RESEARCHER_BASE_URL` | OpenAI-compatible endpoint | `http://localhost:6655/litellm/v1` |
| `DEEP_RESEARCHER_ANTHROPIC_BASE_URL` | Anthropic endpoint (Claude direct) | `http://localhost:6655/anthropic/v1` |
| `DEEP_RESEARCHER_PROXY_URL` | HTTP proxy for search/fetch | — |
| `DEEP_RESEARCHER_NETWORK_MODE` | `auto` / `proxy` / `direct` | `auto` |
| `DEEP_RESEARCHER_SEMANTIC_MODE` | `hybrid` / `native` | `hybrid` |
| `DEEP_RESEARCHER_WORKSPACE_SOURCES` | Local evidence directories (path-separated) | — |

## Documentation

- [Architecture](docs/architecture.md)
- [Planning Mode](docs/planning-mode.md)
- [Query Tests](docs/query-tests.md)
