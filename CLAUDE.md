# Deep Researcher — Agent Instructions

## Run Commands

```bash
# Standard run
DEEP_RESEARCHER_API_KEY=4c3e510c-0dcb-4212-8148-b142a009a2aa uv run python -m deep_researcher --question-file queries.json --query-index 1

# Plan only
uv run python -m deep_researcher --plan-only --question-file queries.md --query-index 3

# Mock (offline)
uv run python -m deep_researcher --mock "your question"

# Tests
uv run python -m unittest discover -s tests

# Evaluate a report
uv run python evaluate.py <run_dir>/report.md --no-llm
```

## Architecture

Workflow is role-based: **planner → researcher → writer → verifier**. Each role has its own model candidates list.

- Anthropic models go directly through `anthropic/v1/messages`; all others use `litellm/v1/chat/completions`
- Default model priority: Claude 4.6 first, with GPT-5 / Sonar as fallback
- Global rate limit: 16 RPM (matches restricts.md)

## Semantic Modes

- `hybrid`: planner/verifier produce evidence profiles + source packs, then runtime resolves them into retrieval queries
- `native`: trusts the model to produce complete queries and source paths; runtime only validates and logs

## Evidence & Source System

Evidence gap detection is domain-agnostic. The workflow identifies what *type* of evidence is missing (primary source, benchmark, timeline, quantitative metric, etc.) then generates structured remediation tasks. Financial data sources (Futu, TradingView, CheeseFortune) are optional source packs, not hardcoded.

Configuration files:
- `deep_researcher/evidence_profiles.json`
- `deep_researcher/source_packs.json`
- `deep_researcher/model_capabilities.json`

Override via env vars: `DEEP_RESEARCHER_EVIDENCE_PROFILES_FILE`, `DEEP_RESEARCHER_SOURCE_PACKS_FILE`, `DEEP_RESEARCHER_MODEL_CAPABILITIES_FILE`.

## Context Windows (built-in assumptions)

| Model | Context |
|-------|---------|
| Claude 4.x | 200k |
| GPT-5 / GPT-5 mini / GPT-5 codex | 400k |
| Gemini 2.5 Pro / Flash | 1,048,576 |
| Sonar Pro | 200k |
| Other | 128k |

The router logs `prompt_token_estimate / context_window_tokens / prompt_budget_tokens / max_output_tokens` in trace for debugging.

Note: `*_MAX_OUTPUT_TOKENS` is per-generation cap, not model context window.

## Writing Strategy

Final reports use "per-section writing + lightweight overview assembly" instead of one-shot generation. If section writer or overview fails, falls back to section draft / deterministic overview. Assembled report is validated for completeness.

## Network Mode

`DEEP_RESEARCHER_NETWORK_MODE=auto` probes connectivity first: search determines proxy vs direct, fetch caches per-host results to avoid repeated blind probing.

## Workspace Sources

Supports `txt/md/json/csv/tsv/pdf`. If `--workspace-source` not specified, auto-scans `workspace_sources/`, `workspace/`, `inputs/`, `reports/`.

## Key Files

- `deep_researcher/workflow.py` — main breadth-mode orchestrator
- `deep_researcher/depth_workflow.py` — depth mode (DeepThinker)
- `deep_researcher/prompts.py` — all prompt templates
- `deep_researcher/config.py` — AppConfig, env var loading
- `deep_researcher/llm.py` — LLM router
- `deep_researcher/search.py` — search + fetch with proxy logic
- `deep_researcher/state.py` — ResearchState, checkpoint/resume
- `deep_researcher/semantic_registry.py` — evidence profile / source pack resolution
- `evaluate.py` — report quality evaluation

## Docs

- [docs/architecture.md](docs/architecture.md)
- [docs/planning-mode.md](docs/planning-mode.md)
- [docs/query-tests.md](docs/query-tests.md)
