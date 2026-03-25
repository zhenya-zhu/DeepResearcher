from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from deep_researcher.config import AppConfig
from deep_researcher.depth_workflow import DeepThinker, _topological_sort
from deep_researcher.llm import MockBackend
from deep_researcher.state import DepthState, SubProblem, ThinkingStep, utc_now


class DepthStateTest(unittest.TestCase):
    def test_depth_state_round_trip(self) -> None:
        state = DepthState(
            run_id="test-001",
            question="Prove that the sum of the first n odd numbers equals n squared",
            problem_analysis="Mathematical induction problem.",
            sub_problems=[
                SubProblem(
                    problem_id="base-case",
                    description="Prove the base case for n=1.",
                    status="verified",
                    conclusion="1 = 1 squared. QED.",
                    confidence=1.0,
                    thinking_steps=[
                        ThinkingStep(
                            step_id="step-1",
                            step_type="reason",
                            content="For n=1, the first odd number is 1, and 1^2=1.",
                            confidence=1.0,
                            verification_result="pass",
                        ),
                    ],
                ),
                SubProblem(
                    problem_id="inductive-step",
                    description="Prove the inductive step.",
                    dependencies=["base-case"],
                    status="verified",
                    confidence=0.9,
                ),
            ],
            problem_graph={"base-case": [], "inductive-step": ["base-case"]},
        )
        raw = state.to_dict()
        restored = DepthState.from_dict(raw)
        self.assertEqual(restored.run_id, "test-001")
        self.assertEqual(len(restored.sub_problems), 2)
        self.assertEqual(restored.sub_problems[0].problem_id, "base-case")
        self.assertEqual(restored.sub_problems[0].thinking_steps[0].step_id, "step-1")
        self.assertEqual(restored.sub_problems[1].dependencies, ["base-case"])
        self.assertEqual(restored.problem_graph, {"base-case": [], "inductive-step": ["base-case"]})

    def test_depth_state_load_from_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            state = DepthState(run_id="load-test", question="test question")
            path = Path(temp_dir) / "state.json"
            path.write_text(json.dumps(state.to_dict()), encoding="utf-8")
            loaded = DepthState.load(str(path))
            self.assertEqual(loaded.run_id, "load-test")
            self.assertEqual(loaded.question, "test question")


class TopologicalSortTest(unittest.TestCase):
    def test_linear_dependencies(self) -> None:
        sps = [
            SubProblem(problem_id="c", description="third", dependencies=["b"]),
            SubProblem(problem_id="a", description="first"),
            SubProblem(problem_id="b", description="second", dependencies=["a"]),
        ]
        result = _topological_sort(sps)
        ids = [sp.problem_id for sp in result]
        self.assertEqual(ids, ["a", "b", "c"])

    def test_no_dependencies(self) -> None:
        sps = [
            SubProblem(problem_id="x", description="x"),
            SubProblem(problem_id="y", description="y"),
        ]
        result = _topological_sort(sps)
        self.assertEqual(len(result), 2)

    def test_cycle_breaks_gracefully(self) -> None:
        sps = [
            SubProblem(problem_id="a", description="a", dependencies=["b"]),
            SubProblem(problem_id="b", description="b", dependencies=["a"]),
        ]
        result = _topological_sort(sps)
        self.assertEqual(len(result), 2)


class DepthMockWorkflowTest(unittest.TestCase):
    def test_mock_depth_run_generates_report(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = AppConfig.from_env()
            config.run_root = Path(temp_dir)
            config.use_mock_llm = True
            config.use_mock_tools = True
            config.mode = "depth"

            runner = DeepThinker(config)
            state = runner.run(question="Prove that the sum of the first n odd numbers equals n squared")

            self.assertEqual(state.status, "completed")
            self.assertTrue(len(state.report_markdown) > 0)
            self.assertTrue(len(state.sub_problems) > 0)
            run_dir = Path(runner.run_dir or "")
            self.assertTrue((run_dir / "report.md").exists())
            self.assertTrue((run_dir / "trace.html").exists())
            self.assertTrue((run_dir / "events.jsonl").exists())

    def test_mock_depth_plan_only(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = AppConfig.from_env()
            config.run_root = Path(temp_dir)
            config.use_mock_llm = True
            config.use_mock_tools = True
            config.mode = "depth"

            runner = DeepThinker(config)
            state = runner.plan(question="Design an optimal caching strategy")

            self.assertTrue(len(state.sub_problems) > 0)
            self.assertEqual(state.report_markdown, "")
            run_dir = Path(runner.run_dir or "")
            self.assertTrue((run_dir / "plan.md").exists())
            self.assertTrue((run_dir / "plan.json").exists())

    def test_decomposition_fallback_on_failure(self) -> None:
        class FailingDecomposeBackend(MockBackend):
            def chat(self, model, messages, temperature, max_output_tokens):  # type: ignore[override]
                joined = "\n".join(message["content"] for message in messages)
                if "TASK_KIND: depth_decompose" in joined:
                    raise RuntimeError("decomposition failed")
                return super().chat(model, messages, temperature, max_output_tokens)

        with TemporaryDirectory() as temp_dir:
            config = AppConfig.from_env()
            config.run_root = Path(temp_dir)
            config.use_mock_llm = True
            config.use_mock_tools = True

            runner = DeepThinker(config, backend=FailingDecomposeBackend())
            state = runner.run(question="Simple question")

            self.assertEqual(state.status, "completed")
            self.assertEqual(len(state.sub_problems), 1)
            self.assertEqual(state.sub_problems[0].problem_id, "main")

    def test_verification_fail_triggers_revision(self) -> None:
        class StrictVerifierBackend(MockBackend):
            call_count = 0

            def chat(self, model, messages, temperature, max_output_tokens):  # type: ignore[override]
                joined = "\n".join(message["content"] for message in messages)
                if "TASK_KIND: depth_verify" in joined:
                    StrictVerifierBackend.call_count += 1
                    if StrictVerifierBackend.call_count <= 1:
                        return json.dumps({
                            "overall_verdict": "fail",
                            "step_verdicts": [
                                {"step_id": "step-1", "verdict": "fail", "issues": ["Unsupported assumption"]},
                            ],
                            "critical_issues": ["The reasoning skips a necessary step."],
                            "suggested_revisions": ["Add the missing logical step."],
                        })
                    return json.dumps({
                        "overall_verdict": "pass",
                        "step_verdicts": [],
                        "critical_issues": [],
                        "suggested_revisions": [],
                    })
                return super().chat(model, messages, temperature, max_output_tokens)

        with TemporaryDirectory() as temp_dir:
            config = AppConfig.from_env()
            config.run_root = Path(temp_dir)
            config.use_mock_llm = True
            config.use_mock_tools = True

            runner = DeepThinker(config, backend=StrictVerifierBackend())
            state = runner.run(question="Prove a mathematical theorem")

            self.assertEqual(state.status, "completed")
            # At least one sub-problem should have been revised
            revised_any = any(sp.revision_count > 0 for sp in state.sub_problems)
            self.assertTrue(revised_any)

    def test_all_sub_problems_fail(self) -> None:
        class AlwaysFailVerifier(MockBackend):
            def chat(self, model, messages, temperature, max_output_tokens):  # type: ignore[override]
                joined = "\n".join(message["content"] for message in messages)
                if "TASK_KIND: depth_verify" in joined:
                    return json.dumps({
                        "overall_verdict": "fail",
                        "step_verdicts": [],
                        "critical_issues": ["Fundamental error in reasoning."],
                        "suggested_revisions": ["Start over."],
                    })
                return super().chat(model, messages, temperature, max_output_tokens)

        with TemporaryDirectory() as temp_dir:
            config = AppConfig.from_env()
            config.run_root = Path(temp_dir)
            config.use_mock_llm = True
            config.use_mock_tools = True
            config.max_depth_revisions = 1

            runner = DeepThinker(config, backend=AlwaysFailVerifier())
            state = runner.run(question="Impossible theorem")

            self.assertEqual(state.status, "completed")
            self.assertTrue(len(state.failed_paths) > 0)
            # Report should still be generated
            self.assertTrue(len(state.report_markdown) > 0)

    def test_on_demand_search_triggered(self) -> None:
        class SearchRequestBackend(MockBackend):
            first_think_call = True

            def chat(self, model, messages, temperature, max_output_tokens):  # type: ignore[override]
                joined = "\n".join(message["content"] for message in messages)
                if "TASK_KIND: depth_think" in joined and SearchRequestBackend.first_think_call:
                    SearchRequestBackend.first_think_call = False
                    return json.dumps({
                        "steps": [
                            {"step_id": "step-1", "step_type": "reason",
                             "content": "Need to verify a fact.", "confidence": 0.6},
                        ],
                        "conclusion": "Tentative conclusion pending evidence.",
                        "confidence": 0.6,
                        "needs_search": [
                            {"query": "specific fact verification", "reason": "need external data"},
                        ],
                    })
                return super().chat(model, messages, temperature, max_output_tokens)

        with TemporaryDirectory() as temp_dir:
            config = AppConfig.from_env()
            config.run_root = Path(temp_dir)
            config.use_mock_llm = True
            config.use_mock_tools = True
            config.max_on_demand_searches = 2

            runner = DeepThinker(config, backend=SearchRequestBackend())
            state = runner.run(question="Question requiring evidence")

            self.assertEqual(state.status, "completed")
            # Check that search was triggered
            search_steps = [
                s for s in state.global_reasoning_chain
                if s.step_type == "search_request"
            ]
            self.assertTrue(len(search_steps) > 0)

    def test_resume_from_checkpoint(self) -> None:
        with TemporaryDirectory() as temp_dir:
            # Run first to create a checkpoint
            config = AppConfig.from_env()
            config.run_root = Path(temp_dir)
            config.use_mock_llm = True
            config.use_mock_tools = True

            runner = DeepThinker(config)
            state = runner.run(question="Resume test question")
            self.assertEqual(state.status, "completed")

            # Load the checkpoint and verify it round-trips
            checkpoint_path = Path(runner.run_dir or "") / "checkpoints" / "final.json"
            self.assertTrue(checkpoint_path.exists())
            loaded = DepthState.load(str(checkpoint_path))
            self.assertEqual(loaded.question, "Resume test question")
            self.assertEqual(loaded.status, "completed")


class DepthConfigTest(unittest.TestCase):
    def test_depth_config_defaults(self) -> None:
        config = AppConfig.from_env()
        self.assertEqual(config.mode, "breadth")
        self.assertEqual(config.max_depth_iterations, 5)
        self.assertEqual(config.max_depth_revisions, 3)
        self.assertEqual(config.max_sub_problems, 6)
        self.assertAlmostEqual(config.depth_confidence_threshold, 0.7)
        self.assertEqual(config.max_on_demand_searches, 3)
        self.assertEqual(config.thinker.candidates[0], "anthropic--claude-4.6-opus")
        self.assertEqual(config.thinker.max_output_tokens, 16000)

    def test_depth_config_env_override(self) -> None:
        import os
        old = os.environ.get("DEEP_RESEARCHER_MODE")
        try:
            os.environ["DEEP_RESEARCHER_MODE"] = "depth"
            config = AppConfig.from_env()
            self.assertEqual(config.mode, "depth")
        finally:
            if old is None:
                os.environ.pop("DEEP_RESEARCHER_MODE", None)
            else:
                os.environ["DEEP_RESEARCHER_MODE"] = old


class DepthPromptsTest(unittest.TestCase):
    def test_decomposition_messages_structure(self) -> None:
        from deep_researcher.depth_prompts import build_depth_decomposition_messages
        messages = build_depth_decomposition_messages("test question", 6)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("TASK_KIND: depth_decompose", messages[0]["content"])
        self.assertIn("test question", messages[1]["content"])

    def test_thinking_messages_include_deps(self) -> None:
        from deep_researcher.depth_prompts import build_depth_thinking_messages
        sp = SubProblem(problem_id="test", description="test sub-problem")
        deps = [{"problem_id": "prev", "conclusion": "prior conclusion", "confidence": "0.9", "description": "prev desc", "status": "verified"}]
        messages = build_depth_thinking_messages("question", sp, deps)
        self.assertIn("DEPENDENCY_CONCLUSIONS", messages[1]["content"])
        self.assertIn("prior conclusion", messages[1]["content"])

    def test_verification_messages_structure(self) -> None:
        from deep_researcher.depth_prompts import build_depth_verification_messages
        sp = SubProblem(problem_id="test", description="test")
        steps = [{"step_id": "s1", "step_type": "reason", "content": "test step", "confidence": 0.8}]
        messages = build_depth_verification_messages("question", sp, steps)
        self.assertIn("TASK_KIND: depth_verify", messages[0]["content"])

    def test_revision_messages_structure(self) -> None:
        from deep_researcher.depth_prompts import build_depth_revision_messages
        sp = SubProblem(problem_id="test", description="test")
        steps = [{"step_id": "s1", "step_type": "reason", "content": "original", "confidence": 0.5}]
        feedback = {"overall_verdict": "fail", "critical_issues": ["logical error"]}
        messages = build_depth_revision_messages("question", sp, steps, feedback)
        self.assertIn("TASK_KIND: depth_revise", messages[0]["content"])
        self.assertIn("logical error", messages[1]["content"])

    def test_report_messages_structure(self) -> None:
        from deep_researcher.depth_prompts import build_depth_report_messages
        state = DepthState(
            run_id="test",
            question="test question",
            sub_problems=[
                SubProblem(problem_id="sp1", description="sub 1", status="verified", conclusion="done"),
            ],
        )
        messages = build_depth_report_messages(state)
        self.assertIn("TASK_KIND: depth_report", messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
