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

## P1: Best-of-N Parallel Generation (from Aletheia paper)
**What:** For each sub-problem, run the Think step N times in parallel (N=2-3), verify each, pick the best-scoring one. If none pass, revise the best.
**Why:** Aletheia's key finding: parallel exploration of multiple solution paths dramatically improves quality. Single-path reasoning is fragile — one bad step poisons the chain. Best-of-N gives the system multiple chances.
**Context:** Paper: "Towards Autonomous Mathematics Research" (arxiv 2602.10177v3). Use ThreadPoolExecutor with N=2 default. Each attempt uses different temperature seeds. Verifier scores all attempts, picks highest confidence that passes. Estimated 2x LLM cost per sub-problem but much higher quality.
**Effort:** M (human: ~1 week / CC: ~30 min)
**Depends on:** Depth mode (completed).

## P1: Python Sandbox for Computation
**What:** Add a sandboxed Python execution tool that the Thinker model can invoke during reasoning. Model outputs `needs_computation: [{code, description}]` in its response, system executes code and injects results.
**Why:** Aletheia integrates Python for computation. Our depth mode reasons about formulas but can't verify them numerically. For the coal chemical test, the model derived cost functions but couldn't compute actual breakeven values.
**Context:** Use subprocess with resource limits (timeout=30s, no network, no filesystem). Results injected as evidence into next reasoning step. Tool availability added to thinker prompt when enabled.
**Effort:** M (human: ~3 days / CC: ~45 min)
**Depends on:** Depth mode (completed).

## P2: Confidence-Based Compute Scaling
**What:** Dynamically adjust max_output_tokens based on sub-problem difficulty and intermediate confidence. Easy problems (first-pass confidence >0.85) get shorter budgets. Hard ones (<0.5) get doubled budgets + extended prompts.
**Why:** Aletheia scales inference compute dynamically. Our fixed 16K budget wastes tokens on easy problems and may be insufficient for hard ones.
**Context:** Simple heuristic: if Think returns confidence >0.85 with <4K tokens, halve the budget for similar problems. If confidence <0.5 after full budget, double it for revision. Track and log budget decisions.
**Effort:** S (human: ~2 hrs / CC: ~15 min)
**Depends on:** Depth mode (completed).

## P2: Adversarial Re-Derivation in Verifier
**What:** Instead of just checking reasoning steps, have the Verifier independently re-derive key claims and compare results. Add "what would prove this wrong?" adversarial prompt.
**Why:** Aletheia found that "decoupling a reasoning model's final output from its intermediate thinking tokens enables the model to recognize flaws it initially overlooked." Our verifier currently does checklist-based verification.
**Context:** Add a second verification pass: verifier gets only the conclusion and key claims (not the reasoning chain), attempts independent derivation, then compares. Disagreement triggers revision.
**Effort:** S (human: ~1 day / CC: ~15 min)
**Depends on:** Depth mode (completed).

## P3: Parallel Sub-Problem Reasoning
**What:** Process independent sub-problems (no dependency edges) concurrently using ThreadPoolExecutor.
**Why:** Throughput optimization. Sub-problems without dependencies are embarrassingly parallel.
**Effort:** S (human: ~2 hrs / CC: ~15 min)
**Depends on:** Depth mode (completed).
