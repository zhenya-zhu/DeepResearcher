from typing import Dict, List, Optional
import dataclasses
import datetime as dt
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from urllib.parse import urlsplit

from .config import AppConfig, ModelSelection
from .depth_prompts import (
    build_depth_adversarial_verification_messages,
    build_depth_audit_messages,
    build_depth_decomposition_messages,
    build_depth_report_messages,
    build_depth_revision_messages,
    build_depth_section_report_messages,
    build_depth_thinking_messages,
    build_depth_verification_messages,
)
from .llm import (
    AnthropicCompatibleBackend,
    MockBackend,
    ModelRouter,
    MultiProviderBackend,
    OpenAICompatibleBackend,
)
from .model_capabilities import load_model_capability_registry
from .rate_limit import IntervalRateLimiter
from .search import (
    DDGRSearcher,
    MockFetcher,
    MockSearcher,
    URLFetcher,
    extract_relevant_passages,
)
from .state import (
    AuditIssue,
    DepthState,
    SearchResultRecord,
    SourceRecord,
    SubProblem,
    ThinkingStep,
    utc_now,
)
from .tracing import RunArtifacts


def _run_id() -> str:
    return dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")


def _score_source_credibility(url: str, title: str) -> float:
    _HIGH = {
        "openai.com": 0.95, "anthropic.com": 0.95, "deepmind.google": 0.95,
        "arxiv.org": 0.90, "nature.com": 0.90, "github.com": 0.80,
        "en.wikipedia.org": 0.70, "medium.com": 0.55,
    }
    try:
        host = urlsplit(url).netloc.lower()
    except Exception:
        return 0.5
    if host.startswith("www."):
        host = host[4:]
    if host in _HIGH:
        return _HIGH[host]
    parts = host.split(".")
    if len(parts) > 2:
        parent = ".".join(parts[-2:])
        if parent in _HIGH:
            return _HIGH[parent]
    return 0.5


def _snippet_relevance(query: str, title: str, snippet: str) -> float:
    """Score how relevant a search result is to the query (0.0-1.0).

    Uses term overlap between query and (title + snippet), filtering out
    generic/stopword terms that inflate scores for irrelevant results.
    CJK text is segmented into bigrams since we have no word segmenter.
    """
    # Generic terms that match broadly but don't indicate topical relevance
    _GENERIC_TERMS = {
        # Chinese stopwords / generic query words (bigrams)
        "能够", "取代", "哪些", "什么", "为什", "什么", "如何", "怎么",
        "多少", "是否", "可以", "需要", "包括", "进行", "具有", "通过",
        "以及", "其中", "这些", "那些", "已经", "目前", "当前", "未来",
        "分析", "报告", "研究", "评估", "情况", "布局", "优势", "劣势",
        "技术", "原理", "进展", "发展", "探索", "实现", "综述", "概述",
        "介绍", "背景", "现状", "趋势", "前景", "方向", "方案", "特点",
        "比较", "对比", "总结", "梳理", "解读", "详解", "深度", "全面",
        "最新", "主要", "核心", "关键", "重要", "相关", "一些", "哪一",
        "价格",
        # English generic terms
        "what", "which", "where", "when", "how", "why", "that", "this",
        "these", "those", "can", "could", "would", "should", "about",
        "analysis", "report", "research", "overview", "current", "latest",
        "detail", "details", "some", "many", "most", "other", "also",
        "price", "cost",
    }

    def _tokenize(text: str) -> set:
        """Extract terms: Latin words + CJK bigrams."""
        tokens = set()
        # Latin/digit words (2+ chars)
        for word in re.findall(r"[a-zA-Z0-9]+", text):
            if len(word) >= 2:
                tokens.add(word.lower())
        # CJK bigrams (overlapping)
        cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
        for i in range(len(cjk_chars) - 1):
            tokens.add(cjk_chars[i] + cjk_chars[i + 1])
        return tokens

    q_terms = _tokenize(query)
    # Remove generic terms to focus on topical keywords
    q_terms -= _GENERIC_TERMS
    if not q_terms:
        # All terms were generic; fall back to raw terms
        q_terms = _tokenize(query)
        if not q_terms:
            return 0.5  # can't evaluate
    combined = (title + " " + snippet).lower()
    combined_terms = _tokenize(combined)
    matched = len(q_terms & combined_terms)
    return matched / len(q_terms)


def _compact_search_query(query: str) -> List[str]:
    """Generate search-engine-friendly query variants from potentially verbose CJK queries.

    Returns up to 3 variants, from most specific to broadest.
    """
    # Strip years that confuse search engines
    stripped = re.sub(r"(19|20)\d{2}[\-~年]?\s*", "", query).strip()
    # Extract CJK chunks (sequences of CJK characters) and Latin words
    cjk_chunks = re.findall(r"[\u4e00-\u9fff]+", stripped)
    latin_words = [w for w in re.findall(r"[a-zA-Z]{2,}", stripped)]
    # Filter out generic CJK chunks (single chars or common words)
    _GENERIC_CJK = {
        "中国", "统计", "数据", "最新", "进展", "技术", "分析", "报告",
        "及", "和", "的", "在", "是", "了", "有",
    }
    meaningful_cjk = [c for c in cjk_chunks if len(c) >= 2 and c not in _GENERIC_CJK]

    variants = []
    # Variant 1: All meaningful terms
    all_terms = meaningful_cjk + latin_words
    if all_terms:
        variants.append(" ".join(all_terms[:5]))
    # Variant 2: Key technical terms only (first 3)
    if len(all_terms) > 2:
        variants.append(" ".join(all_terms[:3]))
    # Variant 3: Original query if very different from variants
    compact = re.sub(r"\s+", " ", stripped).strip()
    if compact and (not variants or compact not in variants):
        variants.append(compact[:60])
    return variants or [query[:60]]


def _topological_sort(sub_problems: List[SubProblem]) -> List[SubProblem]:
    by_id = {sp.problem_id: sp for sp in sub_problems}
    visited = set()
    order = []
    in_progress = set()

    def visit(sp_id: str) -> None:
        if sp_id in visited:
            return
        if sp_id in in_progress:
            # Cycle detected — break by skipping
            return
        in_progress.add(sp_id)
        sp = by_id.get(sp_id)
        if sp:
            for dep in sp.dependencies:
                if dep in by_id:
                    visit(dep)
        in_progress.discard(sp_id)
        visited.add(sp_id)
        if sp:
            order.append(sp)

    for sp in sub_problems:
        visit(sp.problem_id)
    return order


class DeepThinker:
    def __init__(
        self,
        config: AppConfig,
        backend: Optional[object] = None,
        searcher: Optional[object] = None,
        fetcher: Optional[object] = None,
    ) -> None:
        self.config = config
        if backend is None:
            if config.use_mock_llm:
                backend = MockBackend()
            else:
                backend = MultiProviderBackend(
                    openai_backend=OpenAICompatibleBackend(
                        base_url=config.base_url,
                        api_key=config.api_key,
                        timeout_seconds=config.timeout_seconds,
                    ),
                    anthropic_backend=AnthropicCompatibleBackend(
                        base_url=config.anthropic_base_url,
                        api_key=config.api_key,
                        anthropic_version=config.anthropic_version,
                        timeout_seconds=config.timeout_seconds,
                    ),
                )
        if searcher is None:
            searcher = (
                MockSearcher()
                if config.use_mock_tools
                else DDGRSearcher(config.proxy_url, config.search_region, network_mode=config.network_mode)
            )
        if fetcher is None:
            fetcher = (
                MockFetcher()
                if config.use_mock_tools
                else URLFetcher(config.proxy_url, config.timeout_seconds, network_mode=config.network_mode)
            )
        self.backend = backend
        self.searcher = searcher
        self.fetcher = fetcher
        effective_rpm = 600 if config.use_mock_llm else config.rpm_limit
        self.rate_limiter = IntervalRateLimiter(effective_rpm)
        self.capability_registry = load_model_capability_registry(config.model_capabilities_file)
        self.tracker: Optional[RunArtifacts] = None
        self.router: Optional[ModelRouter] = None
        self._state_lock = Lock()
        self._search_count = 0
        self._computation_count = 0

    @property
    def run_dir(self) -> Optional[str]:
        if self.tracker is None:
            return None
        return str(self.tracker.run_dir)

    def run(self, question: Optional[str] = None, state: Optional[DepthState] = None) -> DepthState:
        if state is None and not question:
            raise ValueError("question is required when no checkpoint state is provided")
        if state is None:
            state = DepthState(run_id=_run_id(), question=question or "")
        self.tracker = RunArtifacts(self.config.run_root, state.run_id, verbose=self.config.verbose)
        self.router = ModelRouter(self.backend, self.rate_limiter, self.tracker, capability_registry=self.capability_registry)
        self.tracker.log("run", "supervisor", "Run started", data={"question": state.question, "mode": "depth"})

        if not state.sub_problems:
            self._decompose(state)

        self._think_loop(state)
        self._synthesize_report(state)
        self._audit_report(state)

        state.status = "completed"
        self.tracker.write_text("report.md", state.report_markdown)
        self.tracker.checkpoint("final", state)
        self.tracker.log("run", "supervisor", "Run completed", data={"run_dir": str(self.tracker.run_dir)})
        self.tracker.finalize(state)
        return state

    def plan(self, question: Optional[str] = None, state: Optional[DepthState] = None) -> DepthState:
        if state is None and not question:
            raise ValueError("question is required when no checkpoint state is provided")
        if state is None:
            state = DepthState(run_id=_run_id(), question=question or "")
        self.tracker = RunArtifacts(self.config.run_root, state.run_id, verbose=self.config.verbose)
        self.router = ModelRouter(self.backend, self.rate_limiter, self.tracker, capability_registry=self.capability_registry)
        self.tracker.log("run", "supervisor", "Plan-only run started", data={"question": state.question, "mode": "depth"})
        if not state.sub_problems:
            self._decompose(state)
        self.tracker.log("run", "supervisor", "Plan-only run completed", data={"run_dir": str(self.tracker.run_dir)})
        self._render_depth_plan(state)
        self.tracker.finalize(state)
        return state

    # -- Decompose --

    def _decompose(self, state: DepthState) -> None:
        assert self.router is not None
        assert self.tracker is not None
        messages = build_depth_decomposition_messages(
            state.question,
            self.config.max_sub_problems,
        )
        try:
            model, payload = self.router.complete_json("depth-decompose", messages, self.config.planner)
            self.tracker.log("planning", "decomposer", "Decomposition completed", data={"model": model})
        except Exception as exc:
            self.tracker.log("planning", "decomposer", "Decomposition failed, using single problem fallback",
                             level="WARN", data={"error": str(exc)})
            payload = {
                "problem_analysis": "Direct analysis of the question.",
                "reasoning_approach": "Single-problem direct reasoning.",
                "sub_problems": [{"id": "main", "description": state.question, "dependencies": []}],
            }

        state.problem_analysis = payload.get("problem_analysis", "")
        sub_problems = []
        for item in payload.get("sub_problems", [])[:self.config.max_sub_problems]:
            sp_id = item.get("id", "sp-{0}".format(len(sub_problems) + 1))
            sub_problems.append(SubProblem(
                problem_id=sp_id,
                description=item.get("description", ""),
                dependencies=item.get("dependencies", []),
                max_revisions=self.config.max_depth_revisions,
            ))

        if not sub_problems:
            sub_problems = [SubProblem(
                problem_id="main",
                description=state.question,
                max_revisions=self.config.max_depth_revisions,
            )]

        state.sub_problems = sub_problems
        state.problem_graph = {sp.problem_id: sp.dependencies for sp in sub_problems}
        state.status = "decomposed"

        decompose_step = ThinkingStep(
            step_id="decompose-0",
            step_type="decompose",
            content="Decomposed into {0} sub-problems: {1}".format(
                len(sub_problems),
                ", ".join(sp.problem_id for sp in sub_problems),
            ),
        )
        state.global_reasoning_chain.append(decompose_step)
        self.tracker.checkpoint("decomposed", state)

    # -- Think loop --

    def _think_loop(self, state: DepthState) -> None:
        assert self.router is not None
        assert self.tracker is not None
        sorted_problems = _topological_sort(state.sub_problems)
        total_iterations = 0

        for sp in sorted_problems:
            if sp.status in ("verified", "failed"):
                continue
            sp.status = "thinking"
            self.tracker.log("thinking", sp.problem_id, "Thinking about sub-problem",
                             data={"description": sp.description[:100]})

            dep_context = self._gather_dependency_context(state, sp)
            self._think_sub_problem(state, sp, dep_context)
            total_iterations += 1

            if total_iterations >= self.config.max_depth_iterations:
                self.tracker.log("thinking", "supervisor", "Reached max depth iterations",
                                 level="WARN", data={"max": self.config.max_depth_iterations})
                break

        state.status = "thought"
        verified = [sp for sp in state.sub_problems if sp.status == "verified"]
        failed = [sp for sp in state.sub_problems if sp.status == "failed"]
        state.verification_summary = "Verified {0}/{1} sub-problems. Failed: {2}.".format(
            len(verified), len(state.sub_problems), len(failed),
        )
        self.tracker.checkpoint("thought", state)

    def _think_attempt(
        self,
        state: DepthState,
        sp: SubProblem,
        dep_context: List[Dict[str, str]],
        attempt_index: int,
        temperature_offset: float,
    ) -> Optional[Dict]:
        assert self.router is not None
        evidence = self._collect_evidence_for_sub_problem(state, sp)
        messages = build_depth_thinking_messages(
            state.question, sp, dep_context, evidence,
        )
        thinker = self.config.thinker
        if temperature_offset != 0.0:
            new_temp = max(0.0, min(1.0, thinker.temperature + temperature_offset))
            thinker = dataclasses.replace(thinker, temperature=new_temp)
        try:
            model, payload = self.router.complete_json(
                "depth-think-{0}-attempt-{1}".format(sp.problem_id, attempt_index),
                messages, thinker,
            )
            return payload
        except Exception as exc:
            if self.tracker:
                self.tracker.log("thinking", sp.problem_id, "Think attempt {0} failed".format(attempt_index),
                                 level="WARN", data={"error": str(exc)})
            return None

    def _think_sub_problem(
        self,
        state: DepthState,
        sp: SubProblem,
        dep_context: List[Dict[str, str]],
    ) -> None:
        assert self.router is not None
        assert self.tracker is not None

        # Best-of-N parallel generation
        n = self.config.depth_best_of_n
        payload = None
        if n <= 1:
            payload = self._think_attempt(state, sp, dep_context, 0, 0.0)
        else:
            offsets = [0.05 * i for i in range(n)]
            futures = {}
            with ThreadPoolExecutor(max_workers=min(n, 3)) as executor:
                for i in range(n):
                    future = executor.submit(
                        self._think_attempt, state, sp, dep_context, i, offsets[i],
                    )
                    futures[future] = i

            results = []
            for future in as_completed(futures):
                attempt_idx = futures[future]
                try:
                    result = future.result()
                    if result:
                        results.append((attempt_idx, result))
                except Exception:
                    pass

            if results:
                # Pick highest confidence
                best_idx, payload = max(results, key=lambda x: x[1].get("confidence", 0.0))
                state.debug_notes.append(
                    "Best-of-{0}: picked attempt {1} (confidence {2:.2f}) from {3} successful attempts".format(
                        n, best_idx, payload.get("confidence", 0.0), len(results),
                    )
                )
                self.tracker.log("thinking", sp.problem_id, "Best-of-N selected",
                                 data={"n": n, "best_attempt": best_idx, "successful": len(results),
                                        "confidence": payload.get("confidence", 0.0)})

        if payload is None:
            sp.status = "failed"
            state.failed_paths.append("{0}: all thinking attempts failed".format(sp.problem_id))
            return

        self._apply_thinking_result(sp, payload)

        # On-demand computation if requested
        needs_computation = payload.get("needs_computation", [])
        computation_results = []
        if needs_computation and self._computation_count < self.config.max_on_demand_computations:
            for comp_req in needs_computation[:2]:
                code = comp_req.get("code", "")
                description = comp_req.get("description", "")
                if code:
                    result = self._execute_computation(state, sp, code, description)
                    if result and "stdout" in result:
                        computation_results.append(result)

            if computation_results:
                # Re-reason with computation results
                comp_evidence = [
                    {"source_id": "computation", "title": r["description"], "url": "", "excerpt": r["stdout"]}
                    for r in computation_results
                ]
                evidence = self._collect_evidence_for_sub_problem(state, sp) + comp_evidence
                messages = build_depth_thinking_messages(
                    state.question, sp, dep_context, evidence,
                )
                try:
                    model, payload = self.router.complete_json(
                        "depth-think-{0}-with-computation".format(sp.problem_id), messages, self.config.thinker,
                    )
                    self._apply_thinking_result(sp, payload)
                except Exception as exc:
                    self.tracker.log("thinking", sp.problem_id, "Re-thinking with computation failed",
                                     level="WARN", data={"error": str(exc)})

        # On-demand search if requested
        needs_search = payload.get("needs_search", [])
        if needs_search and self._search_count < self.config.max_on_demand_searches:
            for search_req in needs_search[:2]:
                query = search_req.get("query", "")
                if query:
                    self._on_demand_search(state, sp, query)

            # Re-reason with new evidence
            evidence = self._collect_evidence_for_sub_problem(state, sp)
            messages = build_depth_thinking_messages(
                state.question, sp, dep_context, evidence,
            )
            try:
                model, payload = self.router.complete_json(
                    "depth-think-{0}-with-evidence".format(sp.problem_id), messages, self.config.thinker,
                )
                self._apply_thinking_result(sp, payload)
            except Exception as exc:
                self.tracker.log("thinking", sp.problem_id, "Re-thinking with evidence failed",
                                 level="WARN", data={"error": str(exc)})

        # Verify
        verification = self._verify(state, sp)
        if not verification:
            sp.status = "failed"
            state.failed_paths.append("{0}: verification unavailable".format(sp.problem_id))
            return

        verdict = verification.get("overall_verdict", "uncertain")
        if verdict == "pass" and sp.confidence >= self.config.depth_confidence_threshold:
            # Adversarial re-derivation for borderline confidence
            if (self.config.enable_adversarial_verification
                    and sp.confidence < 0.85
                    and sp.confidence >= self.config.depth_confidence_threshold):
                adv_result = self._adversarial_verify(state, sp)
                if adv_result and not adv_result.get("agrees_with_conclusion", True):
                    self.tracker.log("thinking", sp.problem_id,
                                     "Adversarial verifier disagrees, triggering revision",
                                     data={"reason": adv_result.get("disagreement_reason", "")})
                    # Convert adversarial disagreement to verification-like feedback
                    adv_feedback = {
                        "overall_verdict": "fail",
                        "critical_issues": [adv_result.get("disagreement_reason", "Adversarial verifier disagrees")],
                        "step_verdicts": [],
                        "suggested_revisions": ["Address adversarial verifier's concern: {0}".format(
                            adv_result.get("disagreement_reason", ""))],
                    }
                    if sp.revision_count < sp.max_revisions:
                        sp.revision_count += 1
                        sp.status = "revised"
                        revision_result = self._revise(state, sp, adv_feedback)
                        if revision_result:
                            self._apply_thinking_result(sp, revision_result)
                            re_verify = self._verify(state, sp)
                            if re_verify and re_verify.get("overall_verdict") == "pass" and sp.confidence >= self.config.depth_confidence_threshold:
                                sp.status = "verified"
                                self.tracker.log("thinking", sp.problem_id,
                                                 "Sub-problem verified after adversarial revision",
                                                 data={"confidence": sp.confidence})
                                return
                    # Fall through to normal revision loop if adversarial revision didn't resolve
                else:
                    sp.status = "verified"
                    self.tracker.log("thinking", sp.problem_id, "Sub-problem verified (adversarial agrees)",
                                     data={"confidence": sp.confidence})
                    return
            else:
                sp.status = "verified"
                self.tracker.log("thinking", sp.problem_id, "Sub-problem verified",
                                 data={"confidence": sp.confidence})
                return

        # Confidence-based compute scaling for revisions
        revision_thinker: Optional[ModelSelection] = None
        urgency = ""
        base_tokens = self.config.thinker.max_output_tokens
        if sp.confidence >= 0.85:
            revision_thinker = dataclasses.replace(
                self.config.thinker,
                max_output_tokens=max(1000, base_tokens // 2),
            )
            state.debug_notes.append(
                "compute_scale: {0} confidence={1:.2f} >= 0.85, halved tokens to {2}".format(
                    sp.problem_id, sp.confidence, revision_thinker.max_output_tokens,
                )
            )
        elif sp.confidence < 0.5:
            revision_thinker = dataclasses.replace(
                self.config.thinker,
                max_output_tokens=min(32000, base_tokens * 2),
            )
            urgency = "Take extra care: consider alternative approaches, verify each step rigorously."
            state.debug_notes.append(
                "compute_scale: {0} confidence={1:.2f} < 0.5, doubled tokens to {2}, urgency injected".format(
                    sp.problem_id, sp.confidence, revision_thinker.max_output_tokens,
                )
            )

        # Revise loop
        while sp.revision_count < sp.max_revisions:
            sp.revision_count += 1
            sp.status = "revised"
            self.tracker.log("thinking", sp.problem_id, "Revising sub-problem",
                             data={"revision": sp.revision_count, "verdict": verdict})

            revision_result = self._revise(state, sp, verification,
                                           thinker_override=revision_thinker, urgency=urgency)
            if not revision_result:
                break

            self._apply_thinking_result(sp, revision_result)
            verification = self._verify(state, sp)
            if not verification:
                break

            verdict = verification.get("overall_verdict", "uncertain")
            if verdict == "pass" and sp.confidence >= self.config.depth_confidence_threshold:
                sp.status = "verified"
                self.tracker.log("thinking", sp.problem_id, "Sub-problem verified after revision",
                                 data={"confidence": sp.confidence, "revisions": sp.revision_count})
                return

        # Exhausted revisions
        if sp.status != "verified":
            sp.status = "failed"
            state.failed_paths.append(
                "{0}: exhausted {1} revisions, best confidence {2:.2f}".format(
                    sp.problem_id, sp.revision_count, sp.confidence,
                )
            )
            self.tracker.log("thinking", sp.problem_id, "Sub-problem failed after max revisions",
                             level="WARN", data={"revisions": sp.revision_count, "confidence": sp.confidence})

    def _apply_thinking_result(self, sp: SubProblem, payload: Dict) -> None:
        steps = []
        for item in payload.get("steps", []):
            steps.append(ThinkingStep(
                step_id=item.get("step_id", "step-{0}".format(len(steps))),
                step_type=item.get("step_type", "reason"),
                content=item.get("content", ""),
                confidence=item.get("confidence", 0.0),
            ))
        sp.thinking_steps = steps
        sp.conclusion = payload.get("conclusion", "")
        sp.confidence = payload.get("confidence", 0.0)

    def _gather_dependency_context(self, state: DepthState, sp: SubProblem) -> List[Dict[str, str]]:
        context = []
        by_id = {s.problem_id: s for s in state.sub_problems}
        for dep_id in sp.dependencies:
            dep = by_id.get(dep_id)
            if dep and dep.conclusion:
                context.append({
                    "problem_id": dep.problem_id,
                    "description": dep.description,
                    "conclusion": dep.conclusion,
                    "confidence": str(dep.confidence),
                    "status": dep.status,
                })
        return context

    def _collect_evidence_for_sub_problem(self, state: DepthState, sp: SubProblem) -> List[Dict[str, str]]:
        evidence = []
        for sid in sp.source_ids:
            src = state.sources.get(sid)
            if src and src.excerpt:
                evidence.append({
                    "source_id": sid,
                    "title": src.title,
                    "url": src.url,
                    "excerpt": src.excerpt[:self.config.max_chars_per_source],
                })
        return evidence

    # -- Verify --

    def _verify(self, state: DepthState, sp: SubProblem) -> Optional[Dict]:
        assert self.router is not None
        assert self.tracker is not None
        steps_data = [
            {
                "step_id": step.step_id,
                "step_type": step.step_type,
                "content": step.content,
                "confidence": step.confidence,
            }
            for step in sp.thinking_steps
        ]
        messages = build_depth_verification_messages(state.question, sp, steps_data)
        try:
            model, payload = self.router.complete_json(
                "depth-verify-{0}".format(sp.problem_id), messages, self.config.verifier,
            )
            # Apply verification results to steps
            step_verdicts = {v["step_id"]: v for v in payload.get("step_verdicts", [])}
            for step in sp.thinking_steps:
                verdict_data = step_verdicts.get(step.step_id, {})
                step.verification_result = verdict_data.get("verdict", "")
                step.verification_notes = "; ".join(verdict_data.get("issues", []))

            verify_step = ThinkingStep(
                step_id="verify-{0}-r{1}".format(sp.problem_id, sp.revision_count),
                step_type="verify",
                content="Verdict: {0}. Issues: {1}".format(
                    payload.get("overall_verdict", "unknown"),
                    "; ".join(payload.get("critical_issues", [])[:3]) or "none",
                ),
                confidence=sp.confidence,
                verification_result=payload.get("overall_verdict", ""),
            )
            state.global_reasoning_chain.append(verify_step)
            return payload
        except Exception as exc:
            self.tracker.log("thinking", sp.problem_id, "Verification failed",
                             level="ERROR", data={"error": str(exc)})
            return None

    # -- Adversarial Re-Derivation --

    def _adversarial_verify(self, state: DepthState, sp: SubProblem) -> Optional[Dict]:
        assert self.router is not None
        assert self.tracker is not None
        messages = build_depth_adversarial_verification_messages(state.question, sp)
        try:
            model, payload = self.router.complete_json(
                "depth-adversarial-verify-{0}".format(sp.problem_id),
                messages, self.config.verifier,
            )
            adv_step = ThinkingStep(
                step_id="adversarial-{0}".format(sp.problem_id),
                step_type="adversarial_verify",
                content="Agrees: {0}. Reason: {1}".format(
                    payload.get("agrees_with_conclusion", True),
                    payload.get("disagreement_reason", "") or "none",
                ),
                confidence=payload.get("confidence", 0.0),
                verification_result="pass" if payload.get("agrees_with_conclusion", True) else "fail",
            )
            state.global_reasoning_chain.append(adv_step)
            return payload
        except Exception as exc:
            self.tracker.log("thinking", sp.problem_id, "Adversarial verification failed",
                             level="ERROR", data={"error": str(exc)})
            return None

    # -- Revise --

    def _revise(self, state: DepthState, sp: SubProblem, verification: Dict,
                thinker_override: Optional[ModelSelection] = None, urgency: str = "") -> Optional[Dict]:
        assert self.router is not None
        assert self.tracker is not None
        steps_data = [
            {
                "step_id": step.step_id,
                "step_type": step.step_type,
                "content": step.content,
                "confidence": step.confidence,
            }
            for step in sp.thinking_steps
        ]
        messages = build_depth_revision_messages(
            state.question, sp, steps_data, verification, urgency=urgency,
        )
        try:
            model, payload = self.router.complete_json(
                "depth-revise-{0}-r{1}".format(sp.problem_id, sp.revision_count),
                messages, thinker_override or self.config.thinker,
            )

            # Handle on-demand search from revision
            needs_search = payload.get("needs_search", [])
            if needs_search and self._search_count < self.config.max_on_demand_searches:
                for search_req in needs_search[:1]:
                    query = search_req.get("query", "")
                    if query:
                        self._on_demand_search(state, sp, query)

            return payload
        except Exception as exc:
            self.tracker.log("thinking", sp.problem_id, "Revision failed",
                             level="ERROR", data={"error": str(exc)})
            return None

    # -- Computation sandbox --

    _FORBIDDEN_PATTERNS = [
        "import os", "import subprocess", "import sys", "import shutil",
        "import socket", "import ctypes", "import signal",
        "open(", "exec(", "eval(", "__import__", "__builtins__",
        "os.system", "os.popen", "os.exec",
    ]

    def _execute_computation(
        self, state: DepthState, sp: SubProblem, code: str, description: str,
    ) -> Optional[Dict[str, str]]:
        assert self.tracker is not None
        if self._computation_count >= self.config.max_on_demand_computations:
            self.tracker.log("computation", sp.problem_id, "Computation budget exhausted",
                             level="WARN", data={"count": self._computation_count})
            return None

        # Validate against forbidden patterns
        code_lower = code.lower()
        for pattern in self._FORBIDDEN_PATTERNS:
            if pattern.lower() in code_lower:
                self.tracker.log("computation", sp.problem_id, "Forbidden code pattern",
                                 level="WARN", data={"pattern": pattern, "code": code[:200]})
                return {"error_type": "forbidden_pattern", "stderr": "Blocked: {0}".format(pattern), "suggestion": "Remove forbidden import/call"}

        self._computation_count += 1
        state.computation_count = self._computation_count

        wrapper = (
            "import math, statistics, decimal, fractions, itertools, functools, collections, operator\n"
            "{0}\n"
        ).format(code)

        try:
            result = subprocess.run(
                [sys.executable, "-c", wrapper],
                capture_output=True,
                timeout=self.config.computation_timeout_seconds,
                text=True,
                env={},
            )
        except subprocess.TimeoutExpired:
            self.tracker.log("computation", sp.problem_id, "Computation timed out",
                             level="WARN", data={"timeout": self.config.computation_timeout_seconds})
            return {"error_type": "timeout", "stderr": "Execution timed out after {0}s".format(self.config.computation_timeout_seconds), "suggestion": "Simplify the computation"}
        except OSError as exc:
            self.tracker.log("computation", sp.problem_id, "Computation unavailable",
                             level="WARN", data={"error": str(exc)})
            return None

        stdout = (result.stdout or "")[:2000]
        stderr = (result.stderr or "")[:500]

        comp_step = ThinkingStep(
            step_id="computation-{0}-{1}".format(sp.problem_id, self._computation_count),
            step_type="computation",
            content="Computation: {0}\nResult: {1}".format(description, stdout[:200] if stdout else "no output"),
        )
        state.global_reasoning_chain.append(comp_step)

        if result.returncode != 0:
            self.tracker.log("computation", sp.problem_id, "Computation failed",
                             level="WARN", data={"returncode": result.returncode, "stderr": stderr[:200]})
            return {"error_type": "runtime_error", "stderr": stderr, "suggestion": "Fix the code error"}

        self.tracker.log("computation", sp.problem_id, "Computation completed",
                         data={"chars": len(stdout), "description": description[:100]})
        return {"stdout": stdout, "description": description}

    # -- On-demand search --

    def _on_demand_search(self, state: DepthState, sp: SubProblem, query: str) -> None:
        assert self.tracker is not None
        if self._search_count >= self.config.max_on_demand_searches:
            return
        self._search_count += 1
        sp.search_queries_used.append(query)

        search_step = ThinkingStep(
            step_id="search-{0}-{1}".format(sp.problem_id, self._search_count),
            step_type="search_request",
            content="On-demand search: {0}".format(query),
        )
        state.global_reasoning_chain.append(search_step)

        # Try multiple query variants for better search results
        query_variants = _compact_search_query(query)
        all_hits = []
        executed_query = query
        for variant in query_variants:
            try:
                hits = self.searcher.search(variant, limit=self.config.max_results_per_query)
            except Exception as exc:
                self.tracker.log("search", sp.problem_id, "Search variant failed",
                                 level="DEBUG", data={"variant": variant, "error": str(exc)})
                continue
            if hits:
                # Check if any hits pass relevance filter using the ORIGINAL query
                has_relevant = any(
                    _snippet_relevance(query, h.title, h.snippet) >= 0.15
                    for h in hits[:6]
                )
                if has_relevant:
                    all_hits = hits
                    executed_query = variant
                    break
                elif not all_hits:
                    all_hits = hits
                    executed_query = variant

        if not all_hits:
            self.tracker.log("search", sp.problem_id, "On-demand search returned 0 results across all variants",
                             data={"query": query, "variants": query_variants})
            return

        accepted = 0
        for hit in all_hits[:6]:
            # Relevance filter: snippet must share terms with query
            relevance = _snippet_relevance(query, hit.title, hit.snippet)
            if relevance < 0.15:
                self.tracker.log("search", sp.problem_id, "Skipping irrelevant hit",
                                 level="DEBUG", data={"url": hit.url, "relevance": relevance})
                continue

            state.searched_results.append(SearchResultRecord(
                section_id=sp.problem_id,
                raw_query=query,
                executed_query=executed_query,
                title=hit.title,
                url=hit.url,
                snippet=hit.snippet,
            ))
            source = self._register_source(state, query, hit.title, hit.url, hit.snippet)
            self._fetch_source(state, source, query)

            # Post-fetch relevance check: verify excerpt actually has query-relevant content
            if source.excerpt and _snippet_relevance(query, source.title, source.excerpt) < 0.10:
                self.tracker.log("search", sp.problem_id, "Source fetched but content irrelevant, skipping",
                                 level="DEBUG", data={"source_id": source.source_id, "url": source.url})
                continue

            if source.source_id not in sp.source_ids:
                sp.source_ids.append(source.source_id)
            accepted += 1
            if accepted >= 3:
                break

        self.tracker.log("search", sp.problem_id, "On-demand search completed",
                         data={"query": query, "executed_query": executed_query, "hits": len(all_hits), "accepted": accepted})

    def _register_source(self, state: DepthState, query: str, title: str, url: str, snippet: str) -> SourceRecord:
        with self._state_lock:
            for source in state.sources.values():
                if source.url == url:
                    return source
            source_id = "S{0:03d}".format(len(state.sources) + 1)
            source = SourceRecord(
                source_id=source_id,
                query=query,
                title=title,
                url=url,
                snippet=snippet,
                credibility_score=_score_source_credibility(url, title),
            )
            state.sources[source_id] = source
            return source

    def _fetch_source(self, state: DepthState, source: SourceRecord, query: str) -> None:
        assert self.tracker is not None
        if source.fetch_status == "fetched":
            return
        try:
            page = self.fetcher.fetch(source.url)
            source.raw_artifact = page.raw_html[:50000] if page.raw_html else ""
            source.text_artifact = page.text[:self.config.max_chars_per_source * 2]
            source.excerpt = extract_relevant_passages(
                page.text, query, max_chars=self.config.max_chars_per_source,
            )
            source.fetch_status = "fetched"
        except Exception as exc:
            source.fetch_status = "error"
            self.tracker.log("fetch", source.source_id, "Fetch failed",
                             level="WARN", data={"url": source.url, "error": str(exc)})

    # -- Synthesize report --

    def _synthesize_report(self, state: DepthState) -> None:
        assert self.router is not None
        assert self.tracker is not None
        self.tracker.log("writing", "supervisor", "Writing depth report")

        # Write individual sub-problem sections
        section_markdowns = []
        for sp in state.sub_problems:
            messages = build_depth_section_report_messages(state, sp)
            try:
                result = self.router.complete_text(
                    "depth-section-report-{0}".format(sp.problem_id),
                    messages, self.config.writer,
                )
                section_markdowns.append(result.content)
                self.tracker.log("writing", sp.problem_id, "Section report written",
                                 data={"status": sp.status, "chars": len(result.content)})
            except Exception as exc:
                self.tracker.log("writing", sp.problem_id, "Section report failed",
                                 level="WARN", data={"error": str(exc)})
                section_markdowns.append(
                    "## {0}\n\n*Report generation failed for this sub-problem.*\n".format(
                        sp.problem_id
                    )
                )

        # Write overview via full report prompt
        messages = build_depth_report_messages(state)
        try:
            result = self.router.complete_text("depth-report-overview", messages, self.config.writer)
            overview = result.content
        except Exception as exc:
            self.tracker.log("writing", "supervisor", "Overview report failed, using fallback",
                             level="WARN", data={"error": str(exc)})
            overview = "# Deep Analysis Report\n\n**Question:** {0}\n\n**Analysis:** {1}\n".format(
                state.question, state.problem_analysis,
            )

        # Assemble
        parts = [overview]
        for md in section_markdowns:
            parts.append(md)

        # Source appendix — only include sources actually cited in the report
        cited_ids = set(re.findall(r"\[source:(S\d+)\]", "\n".join(parts)))
        if cited_ids:
            parts.append("\n## Sources\n")
            for sid in sorted(cited_ids):
                src = state.sources.get(sid)
                if src:
                    parts.append("- **{0}**: [{1}]({2})".format(sid, src.title[:80], src.url))
        # Note uncited sources for transparency
        uncited = set(state.sources.keys()) - cited_ids
        if uncited:
            parts.append("\n## Searched But Not Cited\n")
            for sid in sorted(uncited):
                src = state.sources.get(sid)
                if src:
                    parts.append("- {0}: [{1}]({2})".format(sid, src.title[:60], src.url))

        state.report_markdown = "\n\n".join(parts)
        self.tracker.log("writing", "supervisor", "Report assembled",
                         data={"chars": len(state.report_markdown), "sub_problems": len(state.sub_problems)})

    # -- Audit --

    def _audit_report(self, state: DepthState) -> None:
        assert self.router is not None
        assert self.tracker is not None
        messages = build_depth_audit_messages(state)
        try:
            model, payload = self.router.complete_json("depth-audit", messages, self.config.verifier)
            for item in payload.get("issues", []):
                state.audit_issues.append(AuditIssue(
                    severity=item.get("severity", "medium"),
                    section_title=item.get("section_title", ""),
                    reason=item.get("reason", ""),
                    suggested_fix=item.get("suggested_fix", ""),
                ))
            self.tracker.log("audit", "auditor", "Audit completed",
                             data={"status": payload.get("status", ""), "issues": len(state.audit_issues)})
        except Exception as exc:
            self.tracker.log("audit", "auditor", "Audit failed",
                             level="ERROR", data={"error": str(exc)})

    # -- Plan rendering --

    def _render_depth_plan(self, state: DepthState) -> None:
        assert self.tracker is not None
        lines = [
            "# Depth Analysis Plan",
            "",
            "Question: {0}".format(state.question),
            "",
            "Mode: `depth`",
            "",
            "## Problem Analysis",
            "",
            state.problem_analysis or "(not generated)",
            "",
            "## Sub-Problems",
            "",
        ]
        for i, sp in enumerate(state.sub_problems, start=1):
            lines.append("### {0}. {1}".format(i, sp.problem_id))
            lines.append("")
            lines.append("Description: {0}".format(sp.description))
            if sp.dependencies:
                lines.append("Dependencies: {0}".format(", ".join(sp.dependencies)))
            lines.append("")

        lines.append("## Dependency Graph")
        lines.append("")
        for sp in state.sub_problems:
            deps = " → ".join(sp.dependencies) if sp.dependencies else "(none)"
            lines.append("- {0}: depends on {1}".format(sp.problem_id, deps))
        lines.append("")

        self.tracker.write_text("plan.md", "\n".join(lines))
        self.tracker.write_json("plan.json", {
            "question": state.question,
            "mode": "depth",
            "problem_analysis": state.problem_analysis,
            "sub_problems": [
                {
                    "problem_id": sp.problem_id,
                    "description": sp.description,
                    "dependencies": sp.dependencies,
                }
                for sp in state.sub_problems
            ],
        })
