import unittest

from deep_researcher.llm import MultiProviderBackend, infer_context_window_tokens, input_budget_tokens


class _FakeBackend:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = []

    def chat(self, model, messages, temperature, max_output_tokens):
        self.calls.append({
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        })
        return self.name


class LlmRoutingTest(unittest.TestCase):
    def test_anthropic_models_use_anthropic_backend(self) -> None:
        openai = _FakeBackend("openai")
        anthropic = _FakeBackend("anthropic")
        backend = MultiProviderBackend(openai_backend=openai, anthropic_backend=anthropic)

        result = backend.chat(
            model="anthropic--claude-4.6-sonnet",
            messages=[{"role": "user", "content": "hello"}],
            temperature=0,
            max_output_tokens=10,
        )

        self.assertEqual(result, "anthropic")
        self.assertEqual(len(anthropic.calls), 1)
        self.assertEqual(len(openai.calls), 0)

    def test_non_anthropic_models_use_openai_backend(self) -> None:
        openai = _FakeBackend("openai")
        anthropic = _FakeBackend("anthropic")
        backend = MultiProviderBackend(openai_backend=openai, anthropic_backend=anthropic)

        result = backend.chat(
            model="gpt-5",
            messages=[{"role": "user", "content": "hello"}],
            temperature=0,
            max_output_tokens=10,
        )

        self.assertEqual(result, "openai")
        self.assertEqual(len(openai.calls), 1)
        self.assertEqual(len(anthropic.calls), 0)

    def test_context_window_defaults_match_model_family(self) -> None:
        self.assertEqual(infer_context_window_tokens("anthropic--claude-4.6-sonnet"), 200000)
        self.assertEqual(infer_context_window_tokens("gpt-5"), 400000)
        self.assertEqual(infer_context_window_tokens("gpt-5-mini"), 400000)
        self.assertEqual(infer_context_window_tokens("gpt-5-chat-latest"), 128000)
        self.assertEqual(infer_context_window_tokens("gemini-2.5-pro"), 1048576)
        self.assertEqual(infer_context_window_tokens("gemini-2.5-flash"), 1048576)
        self.assertEqual(infer_context_window_tokens("sonar-pro"), 200000)
        self.assertEqual(infer_context_window_tokens("sonar"), 128000)

    def test_input_budget_reserves_space_for_generation(self) -> None:
        self.assertEqual(input_budget_tokens("anthropic--claude-4.6-sonnet", 4000), 187808)
        self.assertEqual(input_budget_tokens("gpt-5", 4000), 387808)
        self.assertEqual(input_budget_tokens("gemini-2.5-pro", 4000), 1036384)


if __name__ == "__main__":
    unittest.main()
