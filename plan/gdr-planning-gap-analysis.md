# GDR Planning Gap Analysis

## Goal

对比 `queries.md` 中的 Gemini Deep Research（GDR）reference plan 与当前仓库用真实 planner 产出的 plan，找出结构性差距，并把这些差距转化为 planning 流程优化。

## Inputs

- Query + GDR reference plans: [queries.md](/Users/I561043/SAP/DeepResearcher/queries.md)
- Optimized planning runs:
  - Query 1: [plan.md](/Users/I561043/SAP/DeepResearcher/runs/planning-demo/20260309-142145-618350/plan.md)
  - Query 2: [plan.md](/Users/I561043/SAP/DeepResearcher/runs/planning-demo/20260309-142145-618401/plan.md)
  - Query 3: [plan.md](/Users/I561043/SAP/DeepResearcher/runs/planning-demo/20260309-142145-628306/plan.md)

## What GDR Did Better

- 它不是只给“报告章节”，而是给“研究动作”，所以执行路径更明显。
- 它会显式指出依赖哪些输入材料，尤其是用户上传财报这种私有输入。
- 它会把技术/产业问题拆成更细的比较维度，而不是只按公司名或大主题分组。
- 它会把“这一节必须覆盖的分析点”说得更具体，例如搜索策略、记忆管理、ROE拆解、供应链层级。

## What We Changed

- `queries.md` 解析改为同时支持编号列表、标准 JSON、以及带多行字符串的松散 JSON。
- planning schema 新增：
  - `input_dependencies`
  - `source_requirements`
  - `comparison_axes`
  - section 级 `must_cover`
- section research prompt 现在会继承 `must_cover`，不再只靠 section title/goal。
- planner prompt 增加了几条硬约束：
  - 显式暴露私有输入依赖
  - 比较型任务要列 comparison axes
  - section 内要列 must_cover
  - 输出要保持紧凑，避免超长 JSON 被截断
  - 实体名要和用户问题保持一致，避免引入错误别名
- planner 默认 `max_output_tokens` 从 `4000` 提到 `8000`。

## Comparison Summary

### Query 1: Deep Research 原理与实现

- 旧版我们的 plan 更偏“产品分章节”。
- GDR 明确强调了搜索查询生成、记忆管理、错误纠正、报告生成这些机制维度。
- 新版我们的 plan 已经把这些机制性维度吸收进来：
  - `comparison_axes` 明确列出了搜索策略、推理机制、上下文管理、工具调用、输出生成。
  - section `must_cover` 里补上了查询分解、终止条件、长上下文管理、reflection 等关键点。
- 结论：这一题上，我们已经从“能写报告”提升到“能驱动实现”。

### Query 2: 阳光电源公司研究

- GDR 的强项是非常明确地依赖用户财报，并把竞争对手、市占率、杜邦分析、格雷厄姆/彼得林奇、SWOT 都拆成具体动作。
- 新版我们的 plan 已经补上：
  - `input_dependencies` 直接写出用户上传年报/季报/半年报
  - `source_requirements` 明确三方市占率数据和竞争对手公开数据
  - `must_cover` 中补上产品线、全球布局、杜邦分解、估值框架
- 这题也暴露了一个 planner 风险：模型会把主体实体写歪。为此 prompt 已加入“实体名一致性”约束。
- 结论：这条现在已经可研究，但后续如果要继续提升，可以补一个“用户上传文件清单校验”步骤。

### Query 3: Google TPU 光模块与上游供应链

- GDR 的优势是把技术原理、器件层、供应链层、公司角色层拆得很清楚。
- 新版我们的 plan 已经对齐到类似结构：
  - 技术架构
  - 光模块原理
  - 核心供应商
  - 上游层级结构
  - 行业影响
- 同时我们还多了 `source_requirements` 和 `comparison_axes`，对后续研究执行更有约束。
- 结论：这一题上，新版 plan 已经不弱于 GDR reference plan。

## Remaining Gaps

- 当前 plan 仍然更偏“结构化 research blueprint”，而不是“严格顺序的 execution steps”。
- 对当前 section-driven workflow 来说，这不是 blocker；但如果后面要做更强的执行编排，可以考虑再加一个可选的 `execution_steps` 字段。
- 对于涉及用户私有文件的 query，后续可以把“文件是否已提供、是否可解析”做成 planning 前检查，而不是只写在 plan 里。

## Outcome

这轮优化后，planning 已经从“报告提纲生成器”提升到“带输入依赖、证据要求、比较维度和 section 执行检查点的研究蓝图生成器”。
