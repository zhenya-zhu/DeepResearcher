# Deep Researcher

这个目录现在包含两部分内容：

1. 一份重写后的架构设计文档，直接对原始方案做评估和收敛。
2. 一套最小可运行的 Python 骨架，目标不是“堆最多框架”，而是先把深度研究流程做成可调试、可恢复、可扩展。

## 设计目标

- 不把流程绑定到单一模型或单一厂商。
- 默认适配 `restricts.md` 里的本地 LiteLLM/OpenAI-compatible 网关。
- 对长时任务友好：checkpoint、resume、证据归档、上下文压缩。
- 调试优先：每次运行都会落 `events.jsonl`、`trace.html`、阶段快照、prompt/response 工件。

## 快速开始

先用 `uv` 建虚拟环境并同步项目：

```bash
uv venv .venv
uv sync
```

再准备环境变量。不要把真实 API key 写进代码仓库。

```bash
export DEEP_RESEARCHER_API_KEY="..."
export DEEP_RESEARCHER_BASE_URL="http://localhost:6655/litellm/v1"
export DEEP_RESEARCHER_ANTHROPIC_BASE_URL="http://localhost:6655/anthropic/v1"
export DEEP_RESEARCHER_PROXY_URL=""
```

这里有一个容易混淆的点：配置里的 `*_MAX_OUTPUT_TOKENS` 是单次生成上限，不是模型上下文窗口。
当前代码内置的上下文窗口假设是：

- Claude 4.x: `200k`
- GPT-5 / GPT-5 mini / GPT-5 codex: `400k`
- Gemini 2.5 Pro / Flash: `1,048,576`
- Sonar Pro: `200k`
- 其他未显式识别模型: `128k`

路由器会在 trace 里记录 `prompt_token_estimate / context_window_tokens / prompt_budget_tokens / max_output_tokens`，方便排查长流程上下文是否吃满。

默认模型画像放在 [model_capabilities.json](deep_researcher/model_capabilities.json)。
如果你要覆盖本仓库默认值，可以设置：

```bash
export DEEP_RESEARCHER_MODEL_CAPABILITIES_FILE="/abs/path/model_capabilities.json"
```

运行离线 mock 流程：

```bash
uv run python -m deep_researcher --mock "评估 2026 年企业级 AI Agent 平台格局"
```

运行真实流程：

```bash
uv run python -m deep_researcher "评估 2026 年企业级 AI Agent 平台格局"
```

运行真实 LLM + mock tools 联调：

```bash
uv run python -m deep_researcher --mock-tools --max-rounds 1 "验证本地 6655 鉴权与最小 workflow"
```

先只看 planning 结果：

```bash
uv run python -m deep_researcher --plan-only --question-file queries.md --query-index 3
```

强制使用 Claude 4.6 Sonnet 跑全流程：

```bash
uv run python -m deep_researcher \
  --mock-tools \
  --max-rounds 1 \
  --planner-models anthropic--claude-4.6-sonnet \
  --researcher-models anthropic--claude-4.6-sonnet \
  --writer-models anthropic--claude-4.6-sonnet \
  --verifier-models anthropic--claude-4.6-sonnet \
  "验证 Claude 直连 Anthropic 端点"
```

恢复某次运行：

```bash
uv run python -m deep_researcher --resume runs/20260309-120000/checkpoints/final.json
```

## 输出目录

每次运行会创建一个 `runs/<run_id>/` 目录，核心工件包括：

- `report.md`: 最终报告
- `events.jsonl`: 结构化事件流
- `trace.html`: 可视化时间线
- `plan.md`: planning 结果
- `plan.json`: planning 结构化结果
- `checkpoints/*.json`: 关键阶段快照
- `artifacts/prompts/`: prompt 快照
- `artifacts/responses/`: LLM 返回
- `sources/`: 搜索结果、抓取文本、证据摘要

## 验证

```bash
uv run python -m unittest discover -s tests
```

## Docs

- [docs/README.md](docs/README.md)
- [docs/planning-mode.md](docs/planning-mode.md)
- [docs/query-tests.md](docs/query-tests.md)

## 关键取舍

- 当前实现优先可观测性和稳定恢复，而不是先上复杂并行编排。
- 默认全局限流是 `16 RPM`，与 `restricts.md` 保持一致。
- Anthropic 模型会直接走 `anthropic/v1/messages`，其余模型走 `litellm/v1/chat/completions`。
- 模型选择按角色拆分，并默认优先使用 `Claude 4.6`，同时保留 `GPT-5 / Sonar` fallback。
- 当前内置上下文预算按模型画像推断；输出上限单独由 `*_MAX_OUTPUT_TOKENS` 控制。
