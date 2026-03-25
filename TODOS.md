# TODOS

## P2: Prompt Caching for HAI Proxy
**What:** Add Anthropic `cache_control` markers to system prompts shared across LLM calls.
**Why:** Many calls share identical system prompt + question context. Caching saves ~30% input tokens and reduces latency.
**Context:** HAI proxy at localhost:6655 supports prompt caching. The `llm.py` module already constructs messages — add cache_control to the system message when using Anthropic models. See Anthropic docs on prompt caching.
**Effort:** S (human: ~2 hrs / CC: ~15 min)
**Depends on:** Nothing — can be done anytime after the adaptive agent rewrite.

## P2: Hybrid Breadth+Depth Mode
**What:** Add a `--mode hybrid` that runs breadth search first, then depth reasoning on the most complex findings.
**Why:** Some questions need both wide coverage AND deep analysis. Breadth gathers context, depth reasons over it.
**Effort:** M (human: ~1 week / CC: ~45 min)
**Depends on:** Depth mode (completed).

## P2: Extended Thinking API Integration
**What:** Use Anthropic's `thinking` parameter and model-native chain-of-thought for the thinker role.
**Why:** Native extended thinking may produce better reasoning than prompt-based CoT, especially on hard math/logic problems.
**Effort:** S (human: ~2 hrs / CC: ~15 min)
**Depends on:** Depth mode (completed) + API-level changes in llm.py backends.

## P3: Depth Mode Evaluation Framework
**What:** Add depth-specific scoring rubric to `evaluate.py` — assess logical coherence, reasoning chain quality, verification coverage.
**Why:** Current evaluation is designed for survey reports. Depth reports need different quality metrics.
**Effort:** S (human: ~4 hrs / CC: ~20 min)
**Depends on:** Depth mode (completed).

## P3: Parallel Sub-Problem Reasoning
**What:** Process independent sub-problems (no dependency edges) concurrently using ThreadPoolExecutor.
**Why:** Throughput optimization. Sub-problems without dependencies are embarrassingly parallel.
**Effort:** S (human: ~2 hrs / CC: ~15 min)
**Depends on:** Depth mode (completed).
