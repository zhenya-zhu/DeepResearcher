# Planning Mode

`planning` 是 Deep Research 流程的第一层关卡。它的职责不是给最终答案，而是把开放问题拆成后续可研究、可验证、可落证据的 section。

## 为什么单独测 planning

- 先确认模型会不会把问题拆对。
- 先确认 query 是否可搜索、是否太宽或太窄。
- 在不消耗完整研究成本的情况下快速比较不同模型的规划风格。
- 提前发现 section 边界混乱、成功标准空泛、风险漏项等问题。

## CLI 用法

直接对单个问题做 planning：

```bash
uv run python -m deep_researcher \
  --plan-only \
  "研究一下 Deep Research 的进展和原理"
```

从 [queries.md](queries.md) 里选择第 3 个 query：

```bash
uv run python -m deep_researcher \
  --plan-only \
  --question-file queries.md \
  --query-index 3
```

列出 `queries.md` 中可选的问题：

```bash
uv run python -m deep_researcher \
  --list-queries \
  --question-file queries.md
```

强制 Claude 4.6 Sonnet 做 planning：

```bash
uv run python -m deep_researcher \
  --plan-only \
  --question-file queries.md \
  --query-index 3 \
  --planner-models anthropic--claude-4.6-sonnet
```

## Planning 工件

每次 `--plan-only` 都会写出：

- `plan.md`: 适合人读的 planning 结果
- `plan.json`: 结构化 planning 数据
- `checkpoints/planned.json`: 当时的完整状态快照
- `trace.html`: 过程时间线
- `artifacts/prompts/planning.md`: 发给模型的 prompt
- `artifacts/responses/planning-<model>.md`: 模型原始返回

## 看什么算“plan 质量好”

- `objective` 足够具体，不是复述用户原问题。
- `success_criteria` 能约束后续研究成败。
- `risks` 里包含证据可得性、时效性、数据口径冲突等现实问题。
- `sections` 有清晰边界，不互相重复。
- 每个 section 的 query 既能搜到资料，又能支持后续证据提炼。

## 上下文窗口说明

planning 阶段也会经过同一套路由器，所以 trace 里会记录上下文预算信息。

- `Claude 4.x` 按 `200k context window` 估算
- `GPT-5` 按 `400k context window` 估算
- `Gemini 2.5` 按 `1,048,576 context window` 估算
- `Sonar Pro` 按 `200k context window` 估算
- 未识别模型默认按 `128k` 估算
- `*_MAX_OUTPUT_TOKENS` 只是输出长度上限，不等于上下文窗口
