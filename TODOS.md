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

## P2: Integrate depth_workflow.py with Sonar-Pro Researcher
**What:** Update depth mode (`--mode depth`) to route its researcher to sonar-pro, matching the main workflow.
**Why:** Depth mode currently hardcodes DDGRSearcher. Once the main workflow validates sonar-pro as researcher, depth mode should use the same approach for consistent evidence quality.
**Context:** `depth_workflow.py` instantiates DDGRSearcher directly. Refactor to use the same model routing as the main workflow. Identified during CEO review (2026-03-25).
**Effort:** S (human: ~2 hrs / CC: ~15 min)
**Depends on:** Sonar-pro researcher validation in main workflow.

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

## P3: Cross-Run Evaluation Tracking
**What:** Add automated score history log that tracks composite scores across runs.
**Why:** Currently each eval run is independent. A persistent log makes it easy to see score trends across experiments without manually maintaining TSV files like `results-llm-judge.tsv`.
**Context:** Each run already outputs `METRIC:<score>`. Append to a `scores.jsonl` with timestamp, commit hash, config hash, and all dimension scores. Identified during CEO review (2026-03-25).
**Effort:** S (human: ~2 hrs / CC: ~15 min)
**Depends on:** Nothing — standalone enhancement.
