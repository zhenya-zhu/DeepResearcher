# TODOS

## P2: Prompt Caching for HAI Proxy
**What:** Add Anthropic `cache_control` markers to system prompts shared across LLM calls.
**Why:** Many calls share identical system prompt + question context. Caching saves ~30% input tokens and reduces latency.
**Context:** HAI proxy at localhost:6655 supports prompt caching. The `llm.py` module already constructs messages — add cache_control to the system message when using Anthropic models. See Anthropic docs on prompt caching.
**Effort:** S (human: ~2 hrs / CC: ~15 min)
**Depends on:** Nothing — can be done anytime after the adaptive agent rewrite.
