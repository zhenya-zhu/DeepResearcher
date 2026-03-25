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

自动生成带引用的长篇研究报告

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

# 整体流水线对比

<div class="grid grid-cols-2 gap-4 mt-4 text-sm">
<div class="bg-blue-50 dark:bg-blue-900 rounded-lg p-4">

### Breadth（5 阶段）

```
Planning → Research → Synthesis → Writing → Audit
 规划       迭代搜索    跨章综合     写-批-改    质检
(1次LLM)  (最多3轮)   (统一口径)  (Write+Critique  (全局)
                                   +Revise)
```

</div>
<div class="bg-green-50 dark:bg-green-900 rounded-lg p-4">

### Depth（4 阶段）

```
Decompose → Think Loop → Synthesize → Audit
 分解子问题    推理循环       报告生成     质检
(1次LLM)   (Think→Verify  (逐章节+总览)  (逻辑
            →Revise ×N)                一致性)
```

</div>
</div>

<v-click>

<div class="mt-4 text-center">

> 两种模式共享基础设施：LLM Router / 搜索引擎 / Tracing / 检查点 / 速率限制

</div>

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

<div class="mt-4 text-sm">

```json
// Depth 分解示例
{
  "sub_problems": [
    {"id": "product-taxonomy", "description": "煤化工能替代哪些石油化工产品", "dependencies": []},
    {"id": "tech-routes", "description": "主要技术路线及成本结构", "dependencies": ["product-taxonomy"]},
    {"id": "breakeven-price", "description": "各产品的临界油价", "dependencies": ["tech-routes"]}
  ]
}
```

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
Round 1: 初始搜索（每章节 3-4 条查询 × 3 种变体）
    ↓
Gap Review: Verifier 评估证据充分度 (0-5 分)
    ↓                              ↓
sufficiency < 3.5               证据充分
或有 gap_tasks                      ↓
    ↓                          → Synthesis
Round 2: 定向补充（Gap Review 生成的新查询）
    ↓
Gap Review → ... → Round 3 (最多) → Synthesis
```

</div>

<v-clicks>

- **并行执行**：`ThreadPoolExecutor` 最多 3 workers
- **搜索变体**：紧凑版 / 去年份版 / 主题聚焦版 — 首次命中即停
- **段落提取**：不把整个网页传给 LLM，只截取相关段落 → 节省 token
- **可信度评分**：arxiv 0.90 / github 0.80 / wikipedia 0.70 / medium 0.55 / reddit 0.40

</v-clicks>

<v-click>

> 类比：搜 "煤化工技术" → 发现 "费托合成" → 第二轮针对性搜费托合成细节

</v-click>

---

# Depth: Think → Verify → Revise 循环

**越想越深，自我纠错**

```
对每个子问题（按拓扑排序）:

┌→ [REASON] ── thinker LLM (16K tokens 输出)
│    构建推理链：每步有 content + confidence
│    如需外部事实 → 触发按需搜索（最少搜索原则）
│
├→ [VERIFY] ── verifier LLM (temperature=0.0)
│    检查：逻辑错误 / 无支撑假设 / 循环论证 / 跳步
│    通过 → 标记 "verified"
│    失败 → 进入修正
│
└→ [REVISE] ── thinker + 验证反馈（最多 3 次）
     修复具体步骤 / 补充遗漏环节 / 提出全新思路
     仍失败 → 记录为 "failed path"，继续下一个子问题
```

<v-click>

<div class="mt-2">

> **关键区别**：Breadth 的迭代是"搜更多"，Depth 的迭代是"想更深"

</div>

</v-click>

---

# Depth: 按需搜索 vs Breadth: 大量搜索

<div class="grid grid-cols-2 gap-6 mt-4">
<div>

### Breadth: 搜索为主

- 每章节 3-4 条查询
- 每条查询 3 种变体
- 最多 3 轮迭代
- **总搜索量：30-50 次**
- 链接跟踪：可信度 ≥ 0.8 的前 3 条

</div>
<div>

### Depth: 搜索为辅

- 推理过程中**按需触发**
- 模型说 `needs_search` 才搜
- 最多 3 次搜索（硬上限）
- **总搜索量：0-3 次**
- **相关性过滤**：
  - 搜索结果：snippet 相关度 ≥ 0.15
  - 抓取内容：正文相关度 ≥ 0.10
  - 不相关来源直接丢弃

</div>
</div>

<v-click>

<div class="mt-4">

> Depth 模式的搜索是 **"我需要一个事实来支撑推理"**，不是 **"让我看看有什么信息"**

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
5. **失败记录** — 被否定的推理路径也保留

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
- Verifier 打分 0-5
- `sufficiency < 3.5` → 强制继续搜索
- 输出 `gap_tasks` 注入下一轮

**2. Write-Critique-Revise（写作阶段）**
- 独立 Verifier 打分 1-10
- 分数 < 8 → 触发修改
- 检查：结构 / 深度 / 证据 / 连贯

**3. Audit（终审）**
- 无支撑论断 / 弱引用 / 缺失内容

</div>
<div class="border-l-4 border-green-400 pl-4">

### Depth: 两层质控

**1. Verify-Revise（推理阶段）**
- Verifier 逐步检查推理链
- 检查：逻辑错误 / 循环论证 / 跳步
- confidence < 0.7 → 标记不确定
- 失败 → 最多 3 次修正

**2. Audit（终审）**
- 验证逻辑一致性
- 检查引用真实性（**只引已验证来源**）
- 确认所有子问题都被覆盖

> Depth 的质控在推理阶段**更严格** — 验证的是逻辑链，不只是证据覆盖

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
| **Planner** | 设计章节 + 搜索查询 | 分解子问题 + 依赖图 | 0.2 | 5K |
| **Researcher** | 分析证据、提炼论点 | — | 0.2 | 5K |
| **Thinker** | — | 深度推理链 | 0.3 | **16K** |
| **Writer** | 撰写章节 Markdown | 撰写章节 Markdown | 0.2 | 5K |
| **Verifier** | Gap Review + Critique + Audit | Verify + Audit | **0.0** | 5K |
| **Fast** | 轻量任务 | — | 0.1 | 2K |

</div>

<v-click>

<div class="mt-4 text-sm">

- **Thinker** 是 Depth 模式独有角色 — 需要长输出（16K tokens）来展开推理链
- 多模型 + 自动 fallback：claude-4.6-sonnet → gpt-5 → sonar-pro
- HAI Proxy (`localhost:6655`) 统一调用，16 RPM 限流
- Depth 实测 Sonnet 足够好，不需要 Opus（Opus 容易超时）

</div>

</v-click>

---

# 资源使用对比

<div class="text-sm mt-4">

| 维度 | Breadth | Depth |
|------|---------|-------|
| LLM 调用次数 | ~30+ (plan + 6 sections × search + gap review + write-critique-revise + report) | ~15-20 (decompose + think + verify + revise + report) |
| 搜索查询 | 大量（每章节 3-4 × 3 变体 × 最多 3 轮） | 极少（最多 3 次按需搜索） |
| 单次输出长度 | 短（结构化 JSON，~1-2K tokens） | 长（推理链，~8-16K tokens） |
| 典型用时 | ~15-25 分钟 | ~30-45 分钟 |
| 核心开销 | 搜索 + 网页抓取（网络 I/O） | LLM 推理（计算） |
| Token 总消耗 | 中等（多次短调用） | 高（少次长调用） |

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
| 研究/推理 | LLM 分析失败 → 启发式 findings | Verify 始终失败 → max_revisions 兜底 |
| 搜索 | 零结果 → 查询变体（最多 3 种） | 搜索失败 → 跳过，继续推理 |
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

# 首次 Depth 测试：煤化工深度分析

**问题：** 煤化工能够取代石油化工的哪一些产物？在什么价格上能够取代？

<div class="grid grid-cols-2 gap-6 mt-4 text-sm">
<div>

### 运行统计
- ⏱️ 总时长：45 分钟
- 🧩 子问题：6 个
- ✅ 验证通过：3 个
- ❌ 修正后失败：2 个
- ⏹️ 达到迭代上限：1 个
- 🔍 按需搜索：3 次
- 📄 报告长度：~550 行

</div>
<div>

### 报告内容亮点
- 产品谱系四层分类（A/B/C/D 类）
- 乙烯成本函数推导（含联产品抵扣）
- 煤制烯烃临界油价公式
- 煤价敏感性分析（+100元/吨 → +9$/桶）
- 碳价影响建模
- **被否定的分析路径（4 条）**

</div>
</div>

<v-click>

<div class="mt-2">

> Think → Verify → Revise 循环工作良好：模型主动否定了斜率 8.5 的简化模型，修正为 16.54 的联产品抵扣模型

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
+-----+          +----+-----+
|     |          |    |      |
plan  research   decompose think synthesize
      |               |
      +---- [共享基础设施] ----+
      |  LLM Router (ModelRouter)  |
      |  Search (DDGRSearcher)     |
      |  Trace (RunArtifacts)      |
      |  Config (AppConfig)        |
      |  Rate Limit                |
      +----------------------------+
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
    #   source_ids
    problem_graph: Dict[str, List[str]]
    verification_summary: str
    failed_paths: List[str]
    sources: Dict[str, SourceRecord]
    report_markdown: str
```

重心：**子问题 × 推理链 × 验证结果**

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

### LLM 评分（0-10）

- Structure & Organization
- Depth & Reasoning
- Evidence & Citations
- Narrative Coherence
- Completeness

</div>
</div>

<v-click>

```bash
uv run python evaluate.py runs/<id>/report.md --no-llm  # 仅结构指标
uv run python evaluate.py runs/<id>/report.md            # 完整评估
```

</v-click>

<v-click>

<div class="mt-2 text-sm">

> TODO: Depth 模式需要专门的评估维度 — 逻辑链质量、推理深度、纠错效果

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
| Thinker 模型 | Sonnet-first + 300s 超时 | Opus 推理容易超时，Sonnet 够用 |
| 搜索策略 | Depth 按需最少搜索 | 推理为主，搜索为辅 |
| 引用规则 | 只引已验证来源 + 相关性过滤 | 防止编造引用 |
| 共享基础设施 | LLM Router / Search / Trace | 不重复造轮子 |

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

⚖️ **多层质控** — Gap Review / Verify-Revise / Audit

</div>
<div>

🛡️ **处处容错** — 永远能产出

🔗 **两种搜索哲学** — 大量搜索 vs 按需最少搜索

📊 **引用可信** — 相关性过滤 + 防伪造

🔍 **可审计** — 失败路径、未引用来源都记录

</div>
</div>

---
layout: center
class: text-center
---

# Q & A

代码：`workflow.py`（breadth）| `depth_workflow.py`（depth）

文档：`docs/architecture.md`

<br>

```bash
# Breadth（默认）
DEEP_RESEARCHER_API_KEY=<key> uv run python -m deep_researcher \
  --question "你感兴趣的任何研究问题"

# Depth
DEEP_RESEARCHER_API_KEY=<key> uv run python -m deep_researcher \
  --mode depth --question "需要深度分析的复杂问题"
```
