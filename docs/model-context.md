# Model Context

这个项目现在显式区分两件事：

- `context window`: 模型可接收的总上下文能力
- `max_output_tokens`: 单次生成输出上限

不要把这两个概念混在一起。把 API 请求里的 `max_tokens` 直接设成 `128k` 或 `200k`，通常表示“允许模型一次性生成超长输出”，不是“模型拥有这么长的上下文窗口”。

默认模型画像现在不再写死在代码里，而是放在 [model_capabilities.json](deep_researcher/model_capabilities.json)。

## 当前默认假设

- `Claude 4.x`：`200k context window`
- `GPT-5 / GPT-5 mini / GPT-5 codex`：`400k context window`
- `Gemini 2.5 Pro / Flash`：`1,048,576 context window`
- `Sonar Pro`：`200k context window`
- `Sonar / Sonar Reasoning Pro / Sonar Deep Research`：`128k context window`
- 其他未识别模型：默认 `128k context window`

这个假设目前由路由器根据模型名推断，用于：

- 记录 `prompt_token_estimate`
- 记录 `context_window_tokens`
- 记录 `prompt_budget_tokens`
- 提前发现长流程里 prompt 接近上限的情况

trace 里还会额外记录：

- `model_family`
- `capability_match`
- `capability_match_type`
- `capability_source_url`

## 当前配置方式

输出上限通过环境变量配置：

```bash
DEEP_RESEARCHER_PLANNER_MAX_OUTPUT_TOKENS=8000
DEEP_RESEARCHER_RESEARCHER_MAX_OUTPUT_TOKENS=2200
DEEP_RESEARCHER_WRITER_MAX_OUTPUT_TOKENS=8000
DEEP_RESEARCHER_VERIFIER_MAX_OUTPUT_TOKENS=1800
DEEP_RESEARCHER_FAST_MAX_OUTPUT_TOKENS=1000
```

为了兼容旧配置，`*_MAX_TOKENS` 仍然可读，但后续建议统一使用 `*_MAX_OUTPUT_TOKENS`。

如果你要覆盖默认模型画像，可以设置：

```bash
DEEP_RESEARCHER_MODEL_CAPABILITIES_FILE=/abs/path/model_capabilities.json
```

自定义文件格式和包内默认文件保持一致。

## Trace 里怎么看

查看一次 run 的 [trace.html](runs/20260309-102803-488320/trace.html) 时，重点看 `llm` 和 `context` 事件里的这些字段：

- `prompt_token_estimate`
- `context_window_tokens`
- `prompt_budget_tokens`
- `max_output_tokens`

如果 `prompt_token_estimate` 明显逼近 `prompt_budget_tokens`，就说明下一步应该收紧 section 边界、减少单轮证据包，或者引入分段总结，而不是继续盲目增大输出上限。
