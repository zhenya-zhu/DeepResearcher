---
theme: default
title: 'DeepResearcher: 双模式深度研究代理'
info: |
  自动化研究报告生成系统 — Breadth + Depth 双模式架构
class: text-center
drawings:
  persist: false
transition: slide-left
mdc: true
---

# DeepResearcher

**双模式深度研究代理**

Breadth（广度搜索） + Depth（深度推理）

自动生成长篇研究报告

记得录屏

---
layout: center
---

# 为什么做这个？

<v-clicks>

- 一个深度研究需要 **搜索几十个来源** → 人工耗时数小时
- LLM 直接写报告？→ **幻觉、无引用、结构涣散**
- 不同问题需要不同策略：
  - "煤化工行业全景分析" → **广度**搜索、多来源交叉
  - "煤制烯烃的临界油价是多少" → **深度**推理、公式推导
- 我们需要的是：**两种模式 — 像学者综述 vs 像工程师解题**

</v-clicks>

---

# 两种研究模式

<div class="grid grid-cols-2 gap-8 mt-4">
<div class="border-2 border-blue-400 rounded-lg p-4">

### Breadth Mode（广度搜索）

- 适合 **"Map the landscape of X"**
- **搜索驱动**：5-6 章节 × 多轮搜索
- 越查越深，不是盲目重复
- 输出：**多章节调查报告**
- 强项：覆盖面广、来源丰富

</div>
<div class="border-2 border-green-400 rounded-lg p-4">

### Depth Mode（深度推理）

- 适合 **"Solve this hard problem"**
- **推理驱动**：分解 → 思考 → 验证 → 修正
- 越想越深，自我纠错
- 输出：**深度分析 + 公式推导**
- 强项：逻辑严密、多情景分析

</div>
</div>

<v-click>

<div class="mt-4 text-center">

> 类比：Google 有 **Deep Research**（广度）和 **DeepThink**（深度），我们两种都做

</div>

</v-click>

---

# 核心理念对比

<div class="grid grid-cols-2 gap-8 mt-4">
<div>

### 共同点

- ✅ 拆解问题为结构化子任务
- ✅ 迭代加深，不是一次就停
- ✅ 多层质控（验证 + 审计）
- ✅ 处处容错，永远能产出
- ✅ 研究与写作分离

</div>
<div>

### 不同点

| | Breadth | Depth |
|---|---------|-------|
| 核心动作 | **搜索** | **推理** |
| 拆解方式 | 章节 | 子问题 |
| 迭代方式 | Gap Review | Verify→Revise |
| 外部依赖 | 大量搜索 | 按需最少搜索 |
| 输出风格 | 综述报告 | 深度分析 |

</div>
</div>

---
layout: center
---

# Breadth 流水线（5 阶段）

```
┌──────────┐    ┌───────────────────────┐    ┌──────────────┐    ┌──────────────────┐    ┌─────────┐
│ Planning  │ →  │  Iterative Research   │ →  │  Synthesis    │ →  │    Writing       │ →  │  Audit  │
│ 规划      │    │  迭代搜索（最多3轮）    │    │  跨章节综合   │    │  写 → 批 → 改    │    │  质检   │
└──────────┘    └───────────────────────┘    └──────────────┘    └──────────────────┘    └─────────┘
```

<div class="grid grid-cols-5 gap-2 mt-4 text-xs">
<div class="border rounded p-2">

**Planning**
- Planner LLM 1 次调用
- 输出 5-7 个章节
- 每章节带搜索查询
- evidence_requirements
- Semantic Registry 解析

</div>
<div class="border rounded p-2">

**Research ×3**
- 本地证据收集
- 查询归一化 + 变体
- DuckDuckGo 搜索
- 网页抓取 + 段落提取
- 链接跟踪（可信度≥0.8，⚠️ 可能过严）
- Researcher LLM 分析
- **Gap Review** → 定向补充

</div>
<div class="border rounded p-2">

**Synthesis**
- 跨章节矛盾检测
- 重叠内容标记
- cross_cutting_themes
- 给每个 Writer 上下文

</div>
<div class="border rounded p-2">

**Writing**
- Writer LLM 写初稿
- Verifier 独立打分
- 分数 < 8 → 修改
- Executive Summary
- Conclusion
- 来源附录

</div>
<div class="border rounded p-2">

**Audit**
- 全局质检
- 无支撑论断
- meta-commentary
- false confidence
- 报告完整性验证

</div>
</div>

<v-click>

> 核心思路：**搜索驱动**，像学者做综述 — 先列提纲，按提纲搜资料，反复补缺，最后统一写作

</v-click>

---

# Depth 流水线（4 阶段 + Aletheia 增强）

```
┌───────────┐    ┌─────────────────────────────────────────┐    ┌───────────┐    ┌─────────┐
│ Decompose  │ →  │             Think Loop                  │ →  │ Synthesize │ →  │  Audit  │
│ 分解子问题 │    │  按拓扑序逐一处理每个子问题                │    │ 报告生成   │    │  质检   │
└───────────┘    └─────────────────────────────────────────┘    └───────────┘    └─────────┘
```

<div class="grid grid-cols-4 gap-2 mt-4 text-xs">
<div class="border rounded p-2">

**Decompose**
- Planner LLM 1 次调用
- 输出 4-6 个子问题
- 每个带依赖列表
- 拓扑排序确保顺序
- Fallback: 单子问题

</div>
<div class="border rounded p-2 border-green-400">

**Think Loop** ← 核心
- **Best-of-N** 并行推理（可选）
- Thinker LLM 16K 输出
- `needs_computation` → **Python 沙箱**
- `needs_search` → 按需搜索（≤3次）
- **Verify** → 逐步检查推理链
- **Adversarial** → 独立重推导（可选）
- **Revise** → 防截断上限 + urgency 提示
- confidence < 0.7 → 继续修正

</div>
<div class="border rounded p-2">

**Synthesize**
- 每个子问题 → 独立章节
- 全局总览报告
- 失败路径展示
- Sources（仅引用的）
- Searched Not Cited

</div>
<div class="border rounded p-2">

**Audit**
- 逻辑一致性
- 引用真实性
- 所有子问题覆盖
- 推导正确性

</div>
</div>

<v-click>

> 核心思路：**推理驱动**，像工程师解题 — 拆解问题，逐步推理验证，自我纠错，展示思考过程

</v-click>

---

# 实例：煤化工 × Breadth

**问题：** 煤化工能够取代石油化工的哪一些产物？在什么价格上能够取代？

<div class="grid grid-cols-5 gap-1 mt-2 text-xs">
<div class="border rounded p-2 bg-blue-50 dark:bg-blue-900">

**Planning**
- → 5 个章节：
  1. 产品重叠图谱
  2. 煤制烯烃经济性
  3. 乙二醇/合成氨/甲醇
  4. 煤制油与芳烃
  5. 综合竞争力框架
- 每章 5-9 条查询

</div>
<div class="border rounded p-2 bg-blue-50 dark:bg-blue-900">

**Research**
- 35 条查询 × 3 变体
- 3 轮迭代搜索
- **9 个来源**被引用
- Gap Review 定向补充
- 煤制烯烃成本数据
- 碳排放系数

</div>
<div class="border rounded p-2">

**Synthesis**
- 矛盾：经济可行 vs 碳排放约束
- 重叠：多章节讨论成本

</div>
<div class="border rounded p-2">

**Writing**
- 成本对比表格
- CTO 临界油价 $70-80
- 碳强度 13tCO₂/ton

</div>
<div class="border rounded p-2">

**Audit**
- 15 个审计问题
- 部分来源不相关

</div>
</div>

<div class="mt-3 text-sm">

⏱️ **26 分钟** | 📄 232 行 | 🔍 35+ 次搜索 | 🔗 9 来源 — **广而全**，覆盖产品图谱 + 经济性 + 政策 + 碳约束

</div>

---

# 实例：煤化工 × Depth

**同一问题：** 煤化工能够取代石油化工的哪一些产物？在什么价格上能够取代？

<div class="grid grid-cols-4 gap-2 mt-2 text-xs">
<div class="border rounded p-2 bg-green-50 dark:bg-green-900">

**Decompose → 6 子问题**
```
1. 石油化工产品谱系  []
2. 煤化工产品谱系    []
3. 可替代产品交集    [1,2]
4. 成本结构分析      [3]
5. 临界油价计算      [4]
6. 综合评估         [3,5]
```

</div>
<div class="border rounded p-2 bg-green-50 dark:bg-green-900 border-green-400">

**Think Loop**
- ✅ #1 产品谱系 (0.94)
- ✅ #2 煤化工谱系 (0.92)
- ✅ #3 可替代产品 (0.91)
- ❌ #4 成本结构 (0.87)
- ❌ #5 临界油价 (0.78)
- ⏹️ #6 综合评估 (skip)
- 按需搜索仅 **3 次**

</div>
<div class="border rounded p-2">

**Synthesize**
- 四层产品分类体系
- 临界油价公式推导
- 碳敏感性分析
- **被否定的路径**展示

</div>
<div class="border rounded p-2">

**Audit**
- 11 个审计问题
- 煤耗系数不一致
- CTO 临界油价偏差

</div>
</div>

<div class="mt-3 text-sm">

⏱️ **32 分钟** | 📄 457 行 | 🔍 3 次搜索 | 🧠 推理为主 — **深而精**，四层分类 + 临界油价 $35-72 + 碳敏感性 +100元CO₂ = +10.8$/桶

</div>

<v-click>

> **同一问题，两种答法**：Breadth 给你全景地图，Depth 给你计算过程 — 互补，不是替代

</v-click>

---

# Stage 1: 规划阶段

<div class="grid grid-cols-2 gap-6 mt-4">
<div>

### Breadth: 章节规划

**把模糊问题变成结构化研究地图**

<v-clicks>

- Planner LLM 输出 **5-7 个章节**
- 每章节带：标题、研究目标、3-4 条搜索查询
- `must_cover` 检查点 + `evidence_requirements`
- 全局元数据：`objective`, `comparison_axes`

</v-clicks>

</div>
<div>

### Depth: 子问题分解

**把复杂问题拆解为依赖图**

<v-clicks>

- Planner LLM 输出 **4-6 个子问题**
- 每个子问题带：描述 + 依赖列表
- **拓扑排序**确保先解决基础问题
- `problem_analysis` + `reasoning_approach`

</v-clicks>

</div>
</div>

<v-click>

<div class="grid grid-cols-2 gap-4 mt-3 text-xs">
<div>

```json
// Breadth: sections + queries + evidence
{"sections": [
  {"title": "产品重叠图谱",
   "queries": ["煤化工 石油化工 产品对比"],
   "evidence_requirements": ["structural_breakdown"]},
  {"title": "煤制烯烃经济性分析",
   "queries": ["MTO MTP 成本 石脑油裂解"],
   "evidence_requirements": ["quantitative_metric"]},
  {"title": "综合竞争力框架", "...": "..."}
]}
```

</div>
<div>

```json
// Depth: sub_problems + dependencies
{"sub_problems": [
  {"id": "product-taxonomy",
   "description": "煤化工能替代哪些产品",
   "dependencies": []},
  {"id": "tech-routes",
   "description": "主要技术路线及成本结构",
   "dependencies": ["product-taxonomy"]},
  {"id": "breakeven-price",
   "description": "各产品的临界油价",
   "dependencies": ["tech-routes"]}
]}
```

</div>
</div>

</v-click>

---

# Breadth: 搜索基础设施

**搜索是 Breadth 模式的核心引擎**

<div class="grid grid-cols-2 gap-6 mt-2">
<div>

### 查询归一化

LLM 生成的查询太长 → 搜索引擎不买账

```
Before: "分析中国煤化工行业替代
        石油化工的可行性及主要技术路线"
→ DuckDuckGo: 0 条结果 😢

After:  "煤化工 替代 石油化工 技术路线"
→ DuckDuckGo: 大量结果 🎉
```

`_compact_query()` → 分词 → 去停用词 → 压缩到 48 字符

</div>
<div>

### Semantic Registry

把 "需要学术论文" 翻译成 `site:arxiv.org`

| LLM 说的 | Registry 翻译 |
|----------|--------------|
| `primary_source` | `site:arxiv.org` |
| `quantitative_metric` | `benchmark metrics data` |
| `code` | `site:github.com` |

`evidence_profiles.json` + `source_packs.json`

</div>
</div>

---

# Breadth: 迭代搜索循环

**越查越深，不是盲目重复**

<div class="mt-2 text-sm">

```
                  Round 1: 初始搜索
                  每章节 3-4 条查询 × 3 种变体
                         │
                         ▼
              ┌─── Gap Review ───┐
              │  Verifier 打分    │
              │  (0-5 分/章节)    │
              └────┬────────┬────┘
                   │        │
          sufficiency < 3.5  sufficiency ≥ 3.5
          或有 gap_tasks      且无 gap_tasks
                   │        │
                   ▼        ▼
             Round 2     → Synthesis
             定向补充        跨章节综合
                   │
                   ▼
             Gap Review → ... → Round 3 (最多)
```

</div>

<v-clicks>

- **搜索变体**：紧凑版 / 去年份版 / 主题聚焦版 — 首次命中即停
- **可信度评分**：arxiv 0.90 / github 0.80 / wikipedia 0.70 / medium 0.55 / reddit 0.40

</v-clicks>

<v-click>

> 类比：搜 "煤化工技术" → 发现 "费托合成" → 第二轮针对性搜费托合成细节

</v-click>

---

# Depth: Think → Verify → Revise 循环

**越想越深，自我纠错（+ Aletheia 增强）**

```
对每个子问题（按拓扑排序）:

┌→ [REASON] ── thinker LLM (16K tokens 输出)
│    Best-of-N: 并行 N 条推理路径，选最优（可选）
│    如需外部事实 → 触发按需搜索（最少搜索原则）
│    如需数值验证 → 触发计算沙箱（Python sandbox）
│
├→ [VERIFY] ── verifier LLM (temperature=0.0)
│    检查：逻辑错误 / 无支撑假设 / 循环论证 / 跳步
│    通过 + confidence ≥ 0.85 → 直接 verified
│    通过 + confidence 0.7-0.85 → 进入对抗性验证
│    失败 → 进入修正（置信度缩放上限 + urgency 注入）
│
├→ [ADVERSARIAL] ── verifier 独立重推导（可选）
│    只传结论+子问题，隐藏推理链
│    Verifier 从第一性原理独立推导 → 对比原结论
│    不同意 → 触发额外修正
│
└→ [REVISE] ── thinker + 验证反馈（最多 3 次）
     confidence < 0.5 → 输出上限翻倍（防截断）+ urgency 提示
     confidence ≥ 0.85 → 输出上限减半（省成本）
     仍失败 → 记录为 "failed path"
```

<v-click>

<div class="mt-2">

> **关键区别**：Breadth 的迭代是"搜更多"，Depth 的迭代是"想更深"

</div>

</v-click>

---

# Depth: 按需搜索 + 计算沙箱

<div class="grid grid-cols-2 gap-6 mt-4">
<div>

### Breadth: 搜索为主

- 每章节 3-4 条查询
- 每条查询 3 种变体
- 最多 3 轮迭代
- **总搜索量：30-50 次**
- 链接跟踪：可信度 ≥ 0.8 的前 3 条（⚠️ 阈值可能过严）

</div>
<div>

### Depth: 搜索 + 计算为辅

- 推理过程中**按需触发**
- 模型说 `needs_search` 才搜
- 最多 3 次搜索（硬上限）
- **总搜索量：0-3 次**
- 模型说 `needs_computation` → **Python 沙箱**
- 最多 2 次计算（安全沙箱）
- **相关性过滤**：
  - snippet 相关度 ≥ 0.15
  - 正文相关度 ≥ 0.10

</div>
</div>

<v-click>

<div class="mt-4">

> Depth 模式的搜索是 **"我需要一个事实"**，计算是 **"我需要验证一个公式"** — 都是推理的辅助工具

</div>

</v-click>

---

# Depth: 推理链结构化输出

**为什么不让 Thinker 直接写报告？**

<div class="grid grid-cols-2 gap-6 mt-2">
<div>

```json
{
  "steps": [{
    "step_id": "S1",
    "step_type": "reason",
    "content": "煤制烯烃 MTO 路线的单位
      成本由三部分构成：甲醇成本、
      转化成本、联产品抵扣...",
    "confidence": 0.85
  }],
  "conclusion": "临界油价约 55-65 $/bbl",
  "confidence": 0.75,
  "needs_search": [{
    "query": "MTO 甲醇制烯烃 成本数据",
    "reason": "需要实际生产成本验证推导"
  }],
  "needs_computation": [{
    "code": "breakeven = 2850/16.54\nprint(f'{breakeven:.1f}')",
    "description": "计算临界油价"
  }]
}
```

</div>
<div>

<v-clicks>

1. **增量推理** — 每步有独立 confidence 评分
2. **精准验证** — Verifier 逐步检查逻辑链
3. **定向修正** — 只改有问题的步骤
4. **按需搜索** — 推理中发现需要事实才搜
5. **按需计算** — 推理中需要数值验证才算
6. **失败记录** — 被否定的推理路径也保留

</v-clicks>

<v-click>

> 与 Breadth 的 `thesis + findings` 不同，Depth 输出的是**推理过程**，不只是结论

</v-click>

</div>
</div>

---

# 质控机制对比

<div class="grid grid-cols-2 gap-6 mt-4 text-sm">
<div class="border-l-4 border-blue-400 pl-4">

### Breadth: 三层质控

**1. Gap Review（研究阶段）**
- Verifier 打分 0-5，`sufficiency < 3.5` → 继续搜索

**2. Write-Critique-Revise（写作阶段）**
- 独立 Verifier 打分 1-10，< 8 → 触发修改

**3. Audit（终审）**
- 无支撑论断 / 弱引用 / 缺失内容

</div>
<div class="border-l-4 border-green-400 pl-4">

### Depth: 三层质控

**1. Verify-Revise（推理阶段）**
- 逐步检查：逻辑错误 / 循环论证 / 跳步
- 失败 → 最多 3 次修正（上限缩放 + urgency）

**2. Adversarial Re-Derivation（可选）**
- 边界 confidence (0.7-0.85) 触发
- 只传结论，隐藏推理链 → 独立推导 → 对比
- 防止 Verifier 被推理链逐步说服

**3. Audit（终审）**
- 逻辑一致性 + 引用真实性 + 子问题覆盖

> Depth: 标准验证 + 对抗验证 + 终审

</div>
</div>

---

# Depth: 引用防伪造机制

**第一次测试发现的关键问题：模型编造引用**

<v-clicks>

- 搜索返回不相关结果（DVD论坛、百度教程）→ 模型仍然引用它们
- 模型**知道**来源不相关（推理步骤明确说了），但还是引用了
- 根因：prompts 让模型引用"可用来源"，模型就引了所有来源

</v-clicks>

<v-click>

<div class="mt-4">

### 三层解决方案

| 层次 | 机制 | 效果 |
|------|------|------|
| **搜索过滤** | `_snippet_relevance()` — query 词项与标题/摘要重叠度 ≥ 0.15 | 不相关搜索结果直接丢弃 |
| **内容过滤** | 抓取后再次验证正文相关度 ≥ 0.10 | 标题相关但正文无关的也丢弃 |
| **Prompt 规则** | 每个子问题只展示该子问题的 `AVAILABLE_SOURCES`，无来源时明确说"不要编造" | 模型只引用确实支持其论点的来源 |

</div>

</v-click>

<v-click>

> 修复后：**0 条伪造引用**。宁可没有引用，也不造假。

</v-click>

---

# Depth: Aletheia-Inspired 增强

**来自论文 "Towards Autonomous Mathematics Research" (arxiv 2602.10177v3)**

<div class="grid grid-cols-2 gap-6 mt-2 text-sm">
<div>

### Best-of-N 并行生成

- 对每个子问题同时启动 **N 条推理路径**
- 每条路径用不同温度偏移增加多样性
- 选择 confidence 最高的成功路径
- `DEEP_RESEARCHER_DEPTH_BEST_OF_N=2`

### 计算沙箱

- Thinker 返回 `needs_computation` → 执行 Python
- 安全沙箱：禁止 os/subprocess/open/exec
- 预装白名单：math, statistics, decimal...
- 结果注入推理链做数值验证
- 💡 未来可替换为 WASM 沙箱（更强隔离）

</div>
<div>

### 对抗性重推导

- 边界 confidence（0.7-0.85）触发
- **关键：只传结论，不传推理链**
- Verifier 从第一性原理独立推导
- 输出：`independent_reasoning` + `agrees_with_conclusion`
- 不同意 → 触发额外修正

<div class="text-xs text-gray-400 mt-1">

原理：看过推理链的 Verifier 容易被逐步说服（confirmation bias）；<br/>
不看链、只看结论，迫使独立推导 → 能发现整体逻辑漏洞

</div>

### 置信度驱动计算缩放

| confidence | 输出上限 | 实际效果 |
|-----------|----------|---------|
| ≥ 0.85 | **减半**（8K） | 省成本，简单题不需要长链 |
| 0.5-0.85 | 默认 16K | 正常推理 |
| < 0.5 | **翻倍**（32K） | 防截断 + **urgency 提示注入** |

<div class="text-xs text-gray-400 mt-1">

注：上限只防截断，不强制输出更多；真正影响推理行为的是 urgency 提示

</div>

</div>
</div>

<v-click>

> 核心思想：**单路径推理脆弱，并行探索 + 对抗验证 + 动态资源分配 = 更可靠的深度推理**

</v-click>

---

# Cross-Section Synthesis

**Breadth 模式独有 — 防止信息孤岛**

<div class="mt-4 text-sm">

| 检测项 | 说明 |
|-------|------|
| **contradictions** | 章节 A 说"前景广阔"，章节 B 说"严重障碍" |
| **overlaps** | 章节 A 和 C 重复讨论市场规模 |
| **cross_cutting_themes** | 监管风险影响所有章节 |
| **context_brief** | 给每个 Writer 的上下文提示 |

</div>

<v-click>

<div class="mt-6">

- 让 Writer 写每章时感知其他章节上下文 → **内在一致**的报告
- **容错**：失败时跳过，不阻塞写作

</div>

</v-click>

<v-click>

<div class="mt-4">

> Depth 模式不需要 Synthesis — 子问题通过**依赖图**天然有序，结论自动传递给下游子问题

</div>

</v-click>

---

# 报告生成对比

<div class="grid grid-cols-2 gap-6 mt-2 text-sm">
<div>

### Breadth: 写-批-改 循环

| 部分 | 生成方式 |
|------|---------|
| 标题 | LLM 生成（全局视角） |
| Executive Summary | 单独 LLM 调用 |
| 章节 1-N | Write → Critique → Revise |
| Conclusion | LLM 生成 |
| Sources Used | 自动提取 `[source:S0xx]` |
| Not Used | 检索到但未引用 |

每章节独立写，Verifier 独立打分 < 8 → 修改

</div>
<div>

### Depth: 逐子问题报告

| 部分 | 生成方式 |
|------|---------|
| Problem Analysis | 来自 Decompose 阶段 |
| Sub-Problem 1-N | 每个子问题单独章节 |
| Failed Approaches | 被否定的推理路径 |
| Synthesis | 跨子问题综合结论 |
| Sources | **只列实际引用的来源** |
| Searched Not Cited | 搜到但未引用 |

**特色：Failed Approaches 章节** — 展示模型的思考和纠错过程

</div>
</div>

---

# Depth: 结构化输出示例

**从推理链到报告**

```
子问题: "煤制烯烃的临界油价"

Think (Round 1):
  Step 1: MTO 路线成本 = 甲醇成本 + 转化成本 - 联产品收入 (confidence: 0.90)
  Step 2: 假设斜率 8.5 $/bbl per 100元煤价 (confidence: 0.60)
  结论: 临界油价 ≈ 45 $/bbl

Verify: ❌ FAIL
  Issue: "斜率 8.5 忽略了联产品抵扣对边际成本的影响"

Revise (Round 2):
  Step 2': 引入联产品抵扣 → 修正斜率为 16.54 (confidence: 0.80)
  结论: 临界油价 ≈ 55-65 $/bbl

Verify: ✅ PASS

→ 报告中同时展示 "被否定的 8.5 斜率模型" 和 "最终的 16.54 模型"
```

<v-click>

> **这就是 Depth 模式的价值** — 不只给答案，还展示推理过程和自我纠错

</v-click>

---

# 模型角色对比

<div class="text-sm mt-4">

| 角色 | Breadth 中 | Depth 中 | 温度 | 输出上限 |
|------|-----------|---------|------|---------|
| **Planner** | 设计章节 + 搜索查询 | 分解子问题 + 依赖图 | 0.2 | 8K |
| **Researcher** | 分析证据、提炼论点 | — | 0.2 | 5K |
| **Thinker** | — | 深度推理链 + Best-of-N | 0.3 | **16K** |
| **Writer** | 撰写章节 Markdown | 撰写章节 Markdown | 0.2 | 12K |
| **Verifier** | Gap Review + Critique + Audit | Verify + Adversarial + Audit | **0.0** | 8K |
| **Fast** | 轻量任务 | — | 0.1 | 1K |

</div>

<v-click>

<div class="mt-4 text-sm">

- **Thinker** 是 Depth 模式独有角色 — 默认 **Opus-first**，需要长输出（16K tokens）来展开推理链
- 多模型 + 自动 fallback：claude-4.6-opus → claude-4.6-sonnet → gpt-5
- HAI Proxy (`localhost:6655`) 统一调用，16 RPM 限流
- 置信度缩放：hard → 32K 上限 + urgency 提示注入, easy → 8K 上限省成本

</div>

</v-click>

---

# 资源使用对比

<div class="text-sm mt-4">

| 维度 | Breadth | Depth |
|------|---------|-------|
| LLM 调用次数 | ~30+ (plan + sections × search + gap + write-critique-revise) | ~15-25 (decompose + think×N + verify + adversarial + revise + report) |
| 搜索查询 | 大量（每章节 3-4 × 3 变体 × 最多 3 轮） | 极少（最多 3 次按需搜索） |
| 单次输出长度 | 短（结构化 JSON，~1-2K tokens） | 长（推理链，~8-32K tokens，置信度缩放） |
| 典型用时 | ~15-25 分钟 | ~30-45 分钟 |
| 核心开销 | 搜索 + 网页抓取（网络 I/O） | LLM 推理 + 计算沙箱（计算） |
| Token 总消耗 | 中等（多次短调用） | 高（少次长调用，Best-of-N 时 ×2-3） |

</div>

<v-click>

<div class="mt-4">

> Depth 用 **更少但更长** 的 LLM 调用 → 天然更适合速率限制环境（20 RPM）

</div>

</v-click>

---

# 容错设计对比

<div class="text-sm">

| 阶段 | Breadth Fallback | Depth Fallback |
|------|-----------------|----------------|
| 规划/分解 | LLM 超时 → 通用 4 章节模板 | LLM 超时 → 单子问题 = 原问题 |
| 研究/推理 | LLM 分析失败 → 启发式 findings | Best-of-N 全失败 → 标记 failed path |
| 搜索 | 零结果 → 查询变体（最多 3 种） | 搜索失败 → 跳过，继续推理 |
| 计算 | — | 沙箱超时/错误 → 跳过，继续推理 |
| 综合 | LLM 失败 → 跳过 Synthesis | 所有子问题失败 → 输出失败分析报告 |
| 写作 | 截断/失败 → 验证→重试→结构化草稿 | 章节生成失败 → 用结论直接填充 |
| 审计 | Verifier 失败 → 记录通用问题 | Verifier 失败 → 记录通用问题 |

</div>

<v-click>

<div class="mt-4 text-center">

> **两种模式共同原则：宁可输出一份"够用"的报告，也不因某个环节失败而崩溃**

</div>

</v-click>

---

# Depth 测试结果 + Aletheia 增强前后

**问题：** 煤化工能够取代石油化工的哪一些产物？在什么价格上能够取代？

<div class="grid grid-cols-2 gap-6 mt-4 text-sm">
<div>

### V1 测试（基础 Depth）
- ⏱️ 总时长：45 分钟
- 🧩 子问题：6 个
- ✅ 验证通过：3 个
- ❌ 修正后失败：2 个
- ⏹️ 达到迭代上限：1 个
- 🔍 按需搜索：3 次
- 📄 报告长度：~550 行

</div>
<div>

### Aletheia 增强（已实现）
- **Best-of-N**: 并行探索多条推理路径
- **计算沙箱**: 数值验证成本公式
- **对抗性验证**: 边界 confidence 独立推导
- **置信度缩放**: 困难子问题 → 更多 token
- Think → Verify → Revise 循环验证有效：
  - 主动否定斜率 8.5 简化模型
  - 修正为 16.54 联产品抵扣模型

</div>
</div>

<v-click>

<div class="mt-2">

> V1 验证了推理循环的价值；Aletheia 增强让复杂推理更可靠（Best-of-N 防止单路径脆弱、计算沙箱防止公式错误）

</div>

</v-click>

---

# 同一问题，两种模式的差异

<div class="text-sm mt-2">

**问题：煤化工替代石油化工的可行性分析**

| | Breadth 模式 | Depth 模式 |
|---|-------------|-----------|
| **规划** | 6 章节：技术路线、经济性、环保、政策、案例、展望 | 6 子问题：产品分类→技术路线→成本函数→临界油价→非价格约束→结论 |
| **搜索量** | ~40 次 | 3 次 |
| **报告长度** | ~800 行（广而全） | ~550 行（深而精） |
| **引用数** | ~25 条来源 | ~3 条来源（仅必要事实） |
| **独特价值** | 全景覆盖、多角度 | 公式推导、成本建模、敏感性分析 |
| **缺点** | 难以深入单一问题 | 覆盖面有限，依赖模型知识 |

</div>

<v-click>

<div class="mt-4 text-center">

> **互补而非替代** — 用 Breadth 做全景扫描，用 Depth 深入核心问题

</div>

</v-click>

---

# 架构设计：独立但共享

<div class="text-sm">

```
CLI: --mode breadth|depth
            |
  +---------+---------+
  |                   |
mode="breadth"    mode="depth"
  |                   |
DeepResearcher    DeepThinker
(workflow.py)     (depth_workflow.py)
  |                   |
+-----+          +----+-------+
|     |          |    |    |   |
plan  research   decompose think synthesize
      |               |
      +---- [共享基础设施] ----+
      |  LLM Router (ModelRouter)  |
      |  Search (DDGRSearcher)     |
      |  Trace (RunArtifacts)      |
      |  Config (AppConfig)        |
      |  Rate Limit                |
      +----------------------------+
                  |
     [Depth 独有增强]
     Best-of-N / Computation Sandbox
     Adversarial Verify / Confidence Scaling
```

</div>

<v-click>

<div class="mt-2 text-sm">

**关键决策：** 独立 `DeepThinker` 类，不改动现有 `DeepResearcher` — 零风险，单一职责

</div>

</v-click>

---

# 数据结构对比

<div class="grid grid-cols-2 gap-4 text-xs mt-2">
<div>

### Breadth: ResearchState

```python
@dataclass
class ResearchState:
    sections: List[SectionState]
    # 每个 section 有:
    #   queries, findings, thesis,
    #   evidence_sufficiency,
    #   gap_tasks, draft_text
    searched_results: List[SearchResult]
    sources: Dict[str, SourceRecord]
    current_round: int
    report_markdown: str
```

重心：**章节 × 搜索结果 × 证据**

</div>
<div>

### Depth: DepthState

```python
@dataclass
class DepthState:
    sub_problems: List[SubProblem]
    # 每个 SubProblem 有:
    #   thinking_steps, conclusion,
    #   confidence, revision_count,
    #   source_ids, search_queries_used
    problem_graph: Dict[str, List[str]]
    verification_summary: str
    failed_paths: List[str]
    debug_notes: List[str]  # Aletheia 决策日志
    computation_count: int  # 沙箱调用次数
    sources: Dict[str, SourceRecord]
    report_markdown: str
```

重心：**子问题 × 推理链 × 验证 × 计算**

</div>
</div>

<v-click>

<div class="mt-2 text-sm">

> 独立状态类，共享 `SourceRecord` — 组合优于继承

</div>

</v-click>

---

# 检查点与输出

<div class="grid grid-cols-2 gap-4 text-sm mt-2">
<div>

### Breadth

```
runs/{run_id}/
├── report.md
├── plan.md / plan.json
├── trace.html
├── checkpoints/
│   ├── planned.json
│   ├── round-1.json
│   └── final.json
├── sources/
├── artifacts/
└── events.jsonl
```

</div>
<div>

### Depth

```
runs/{run_id}/
├── report.md
├── plan.json
├── trace.html
├── checkpoints/
│   ├── decomposed.json
│   ├── thinking-{id}.json
│   └── final.json
├── sources/
├── artifacts/
│   └── section-{id}.md
└── events.jsonl
```

</div>
</div>

<v-click>

<div class="mt-2">

两种模式都支持 `--resume checkpoints/xxx.json` → 跳过已完成的阶段

</div>

</v-click>

---

# 运行示例

```bash
# Breadth mode（默认）— 广度搜索
DEEP_RESEARCHER_API_KEY=<key> uv run python -m deep_researcher \
  --question "煤化工替代石油化工的可行性分析"

# Depth mode — 深度推理
DEEP_RESEARCHER_API_KEY=<key> uv run python -m deep_researcher \
  --mode depth --question "煤制烯烃的临界油价是多少？"

# 通用选项（两种模式都支持）
--question-file queries.json --query-index 1   # 从文件加载
--workspace-source ./internal-reports/          # 带本地证据
--plan-only                                     # 只看规划
--resume runs/.../checkpoints/round-1.json      # 从检查点恢复
--mock                                          # Mock 模式测试
```

---

# 评估机制

<div class="grid grid-cols-2 gap-8 mt-2">
<div>

### 结构指标（无需 LLM）

- 字数、章节数、表格数
- 引用数（`[source:S0xx]`）
- 唯一来源数、段落数

</div>
<div>

### LLM 评分（9 维度 0-10）

- Structure & Organization
- Depth & Reasoning
- Evidence & Citations
- Narrative Coherence
- Tables & Comparisons
- Paragraph Quality
- Executive Summary & Conclusion
- Completeness
- **Intellectual Honesty** ← new

</div>
</div>

<v-click>

### Composite Score = LLM 60% + 结构 25% + 语义 15%

```bash
uv run python evaluate.py runs/<id>/report.md --no-llm  # 仅结构指标
uv run python evaluate.py runs/<id>/report.md            # 完整 9 维评估
```

</v-click>

<v-click>

<div class="mt-2 text-sm">

> **Intellectual Honesty**: 置信度是否匹配证据强度？推断是否与直接证据区分？有证据支撑的论断是否自信陈述？

</div>

</v-click>

---

# 关键设计决策总结

<div class="text-sm mt-2">

| 决策 | 选择 | 原因 |
|------|------|------|
| 双模式架构 | 独立 `DeepThinker` 类 | 不污染 breadth 代码，单一职责 |
| 状态管理 | `DepthState` vs `ResearchState` 并行 | 不同关注点，组合优于继承 |
| 子问题处理 | 顺序（按拓扑序） | V1 简单可靠，并行留给后续 |
| Thinker 模型 | **Opus-first** + 300s 超时 | Opus 推理质量最佳，配合 Best-of-N |
| 搜索策略 | Depth 按需最少搜索 | 推理为主，搜索为辅 |
| 引用规则 | 只引已验证来源 + 相关性过滤 | 防止编造引用 |
| 共享基础设施 | LLM Router / Search / Trace | 不重复造轮子 |
| Aletheia 增强 | Best-of-N + 计算沙箱 + 对抗验证 + 缩放 | 更可靠的深度推理 |

</div>

---
layout: center
class: text-center
---

# 设计总结

<div class="grid grid-cols-2 gap-6 text-left mt-6">
<div>

🗺️ **先规划再研究** — 带着地图找路

🔄 **迭代加深** — 搜索加深 or 推理加深

🧩 **研究与写作分离** — 结构化数据 → 高质量散文

⚖️ **多层质控** — Gap Review / Verify-Revise / Adversarial / Audit

</div>
<div>

🛡️ **处处容错** — 永远能产出

🔗 **两种搜索哲学** — 大量搜索 vs 按需最少搜索

📊 **引用可信** — 相关性过滤 + 防伪造

🧠 **Aletheia 增强** — Best-of-N / 计算沙箱 / 对抗验证 / 动态缩放

</div>
</div>

---
layout: center
class: text-center
---

# Q & A

代码：`workflow.py`（breadth）| `depth_workflow.py`（depth + Aletheia）

文档：`docs/architecture.md` | 论文：arxiv 2602.10177v3（Aletheia）

<br>

```bash
# Breadth（默认）
DEEP_RESEARCHER_API_KEY=<key> uv run python -m deep_researcher \
  --question "你感兴趣的任何研究问题"

# Depth
DEEP_RESEARCHER_API_KEY=<key> uv run python -m deep_researcher \
  --mode depth --question "需要深度分析的复杂问题"
```
