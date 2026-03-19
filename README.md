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
export DEEP_RESEARCHER_NETWORK_MODE="auto"
export DEEP_RESEARCHER_SEMANTIC_MODE="hybrid"
export DEEP_RESEARCHER_WORKSPACE_SOURCES="workspace_sources"
```

`DEEP_RESEARCHER_NETWORK_MODE` 支持 `auto`、`proxy`、`direct`。默认 `auto` 会先做网络模式探测：search 先判断当前环境更适合直连还是代理，fetch 会按 host 缓存探测结果，避免整轮运行里反复盲试。
`DEEP_RESEARCHER_SEMANTIC_MODE` 支持 `hybrid` 和 `native`。`hybrid` 会把 planner/verifier 给出的 evidence profile 与 source pack 继续解析成 retrieval queries；`native` 则尽量信任模型自己把查询和来源路径说完整，runtime 只做校验、记录和极小 fallback。
`DEEP_RESEARCHER_WORKSPACE_SOURCES` 支持用系统路径分隔符传多个目录或文件；研究阶段会优先从这些本地文档里抽取证据。
workflow 现在不会把补洞逻辑写死在单一领域里。它会先识别当前 section 缺的是哪类证据，例如 `primary source / implementation detail / structural breakdown / benchmark / timeline / quantitative metric / derivation / supply chain`，再把这些缺口转成结构化 remediation tasks，并在下一轮补 query、补 must-cover、强制重查对应 section。对财务市场数据这类特殊场景，`Futu / TradingView / CheeseFortune` 只作为可选 source pack 追加，不参与主流程的领域判断。
这些语义现在由 JSON registry 驱动，而不是散落在 workflow 条件分支里。默认配置文件是 [evidence_profiles.json](deep_researcher/evidence_profiles.json) 和 [source_packs.json](deep_researcher/source_packs.json)，必要时可以通过环境变量覆盖：

```bash
export DEEP_RESEARCHER_EVIDENCE_PROFILES_FILE="/abs/path/evidence_profiles.json"
export DEEP_RESEARCHER_SOURCE_PACKS_FILE="/abs/path/source_packs.json"
```

这里有一个容易混淆的点：配置里的 `*_MAX_OUTPUT_TOKENS` 是单次生成上限，不是模型上下文窗口。
写最终报告时，workflow 现在默认走“逐 section 写作 + 小型 overview 拼装”，不再依赖一次性生成整份长报告。这样可以显著降低 `writer` 超时概率；如果 section writer 或 overview 仍失败，会分别退回到 section draft 和 deterministic overview。最终 assembled report 仍会做完整性校验，避免静默产出半截 `report.md`。
如果任务依赖你本地的年报、季报、半年报、估值表或内部资料，workflow 现在支持把这些文件作为 first-party evidence 接入。支持的格式包括 `txt/md/json/csv/tsv/pdf`；研究阶段会先尝试命中本地文档，再补网页检索。

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

显式指定本地资料目录或文件：

```bash
uv run python -m deep_researcher \
  --workspace-source workspace_sources \
  --workspace-source /abs/path/阳光电源2024年报.pdf \
  --question-file queries.md \
  --query-index 2
```

如果没有显式指定，workflow 会自动扫描 `workspace_sources/`、`workspace/`、`inputs/`、`reports/` 等目录。

运行真实 LLM + mock tools 联调：

```bash
uv run python -m deep_researcher --mock-tools --max-rounds 1 "验证本地 6655 鉴权与最小 workflow"
```

先只看 planning 结果：

```bash
uv run python -m deep_researcher --plan-only --question-file queries.md --query-index 3
```

切换语义解析策略：

```bash
uv run python -m deep_researcher \
  --plan-only \
  --semantic-mode native \
  --question-file queries.md \
  --query-index 3
```

并排对比 `hybrid` 和 `native` 的输出：

```bash
uv run python -m deep_researcher \
  --mock \
  --plan-only \
  --compare-semantic-modes \
  --question-file queries.md \
  --query-index 3
```

这会在 `runs/semantic-compare-*/` 下分别写出 `hybrid/`、`native/` 两套 run，并生成 `comparison.md` 与 `comparison.json`。

`queries.md` 既支持编号列表，也支持带 `query` / `plan` 字段的 JSON 或松散 JSON 列表；其中 `plan` 可作为 reference planning 结果保留在文件里，不会影响正常运行。

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
- `state/workspace-documents.json`: 本地文档 catalog（如果启用了 workspace sources）

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
