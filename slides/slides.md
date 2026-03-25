---
theme: default
title: 'DeepResearcher: 迭代式深度研究代理'
info: |
  自动化研究报告生成系统的架构与设计
class: text-center
drawings:
  persist: false
transition: slide-left
mdc: true
---

# DeepResearcher

**迭代式深度研究代理**

自动生成带引用的长篇研究报告

---
layout: center
---

# 为什么做这个？

<v-clicks>

- 一个深度研究需要 **搜索几十个来源** → 人工耗时数小时
- LLM 直接写报告？→ **幻觉、无引用、结构涣散**
- 搜一次就够了？→ **第一轮搜索往往揭示你不知道自己不知道的东西**
- 我们需要的是：**像人类研究员一样 — 先规划、再搜索、反复补缺、最后写作**

</v-clicks>

---

# 核心理念

<div class="grid grid-cols-2 gap-8 mt-8">
<div>

### 不做什么

- ❌ 一次性让 LLM 写完
- ❌ 搜一轮就停
- ❌ 信任单一来源
- ❌ 写完直接交付

</div>
<div>

### 做什么

- ✅ 拆解为结构化章节
- ✅ 迭代搜索 + 缺口检测
- ✅ 多来源交叉验证
- ✅ 写-批-改 + 终审

</div>
</div>

---
layout: center
---

# 五阶段流水线

```
Planning → Iterative Research → Synthesis → Writing → Audit
 规划          迭代研究          跨章节综合     写作       审计
(1次LLM)     (最多3轮)         (统一口径)   (写+批+改)   (质检)
```

<br>

> 每个阶段有独立的输入/输出边界 → 可从任意检查点恢复

---

# Stage 1: Planning（规划）

**把模糊的问题变成结构化的研究地图**

<v-clicks>

- 用户输入：`"煤化工替代石油化工的可行性分析"`
- Planner LLM 输出 **5-7 个章节**，每个章节带：
  - 标题、研究目标、3-4 条搜索查询
  - `must_cover` 检查点 + `evidence_requirements`
- 全局元数据：`objective`, `comparison_axes`, `success_criteria`, `risks`
  - 为后续所有阶段提供一致的"全局视角"

</v-clicks>

---

# Planning: 查询归一化

**LLM 生成的查询往往太长，搜索引擎不买账**

<div class="grid grid-cols-2 gap-6 mt-4">
<div>

### Before

```
"分析中国煤化工行业替代
石油化工的可行性及主要技术路线"
```

DuckDuckGo: **0 条结果** 😢

</div>
<div>

### After（归一化）

```
"煤化工 替代 石油化工 技术路线"
```

DuckDuckGo: **大量结果** 🎉

</div>
</div>

<v-click>

<div class="mt-4">

`_compact_query()` → 分词 → 去中文停用词 → CJK/Latin 分离 → 压缩到 48 字符

</div>

</v-click>

---

# Planning: Semantic Registry

**把 "需要学术论文" 翻译成 `site:arxiv.org`**

<div class="mt-4 text-sm">

| LLM 说的 | Registry 翻译成 |
|----------|-----------------|
| 需要 `primary_source` | `site:arxiv.org {subject}` / `site:openai.com {subject}` |
| 需要 `quantitative_metric` | `{subject} benchmark metrics data` |
| 需要 `code` | `site:github.com {subject}` |

</div>

<v-click>

<div class="mt-6">

- `evidence_profiles.json` — 定义证据类型（学术、一手、定量…）
- `source_packs.json` — 将类型映射为具体搜索策略
- 两种模式：**hybrid**（运行时展开模板） vs **native**（LLM 直接编码策略）

</div>

</v-click>

---

# Stage 2: Iterative Research（迭代研究）

**越查越深，而不是盲目重复**

<div class="mt-2 text-sm">

```
Round 1: 初始搜索
    ↓
Gap Review: 评估证据充分度 (0-5 分)
    ↓                         ↓
sufficiency < 3.5          证据充分
或有 gap_tasks                ↓
    ↓                    → Synthesis
Round 2: 定向补充
    ↓
Gap Review → ... → Round 3 (最多) → Synthesis
```

</div>

<v-click>

<div class="mt-4">

> 类比：第一轮搜 "煤化工技术" → 发现 "费托合成" 关键词 → 第二轮针对性搜费托合成细节

</div>

</v-click>

---

# Research: 每章节的研究流程

<div class="grid grid-cols-5 gap-2 text-center text-xs mt-4">

<div class="bg-blue-100 dark:bg-blue-900 rounded p-2">

**1. 本地证据**

workspace 文件
BM25 评分

</div>

<div class="bg-green-100 dark:bg-green-900 rounded p-2">

**2. 查询准备**

归一化 +
`site:` 注入

</div>

<div class="bg-yellow-100 dark:bg-yellow-900 rounded p-2">

**3. 搜索抓取**

DDG 搜索
3 变体/查询

</div>

<div class="bg-orange-100 dark:bg-orange-900 rounded p-2">

**4. 链接跟踪**

可信度 ≥ 0.8
最多 3 条

</div>

<div class="bg-red-100 dark:bg-red-900 rounded p-2">

**5. LLM 分析**

thesis +
findings

</div>

</div>

<v-clicks>

<div class="mt-6 text-sm">

- **并行执行**：`ThreadPoolExecutor` 最多 3 workers
- **搜索变体**：紧凑版 / 去年份版 / 主题聚焦版 — 首次命中即停
- **段落提取**：不把整个网页传给 LLM，只截取相关段落 → 节省 token
- **可信度评分**：arxiv 0.90 / github 0.80 / wikipedia 0.70 / medium 0.55 / reddit 0.40

</div>

</v-clicks>

---

# Research: 结构化输出

**为什么不让 Researcher 直接写文章？**

<div class="grid grid-cols-2 gap-6 mt-2">
<div>

```json
{
  "thesis": "费托合成路线在...",
  "key_drivers": ["...", "..."],
  "reasoning_steps": [{
    "observation": "数据显示...",
    "inference": "因此推断...",
    "source_ids": ["S003", "S007"]
  }],
  "findings": [...],
  "follow_up_queries": [...]
}
```

</div>
<div>

<v-clicks>

1. **增量合并** — 多轮 `_merge_findings()`，不覆盖旧发现
2. **精准评估** — Gap Review 逐条检查引用
3. **高质量写作** — Writer 拿到验证过的素材

</v-clicks>

<v-click>

> 研究和写作分离 = 搜一次、写多次

</v-click>

</div>
</div>

---

# Research: Gap Review（缺口审查）

**研究主管：审视证据质量，精准指出缺口**

<v-clicks>

- Verifier LLM 给每章节打 **证据充分度** 评分（0-5 分）
- 输出结构化 `gap_tasks` 注入对应章节
- **自适应判断**：

</v-clicks>

<v-click>

```python
# workflow.py:1415-1421
if avg_sufficiency < 3.5:       # 客观评分太低 → 强制继续
    continue_research = True
if tasks:                        # 有具体缺口任务 → 强制继续
    continue_research = True
```

</v-click>

<v-click>

> Verifier 有时"过早满足" — 硬编码阈值作为安全网

</v-click>

---

# Stage 3: Cross-Section Synthesis

**防止信息孤岛：章节 A 说"前景广阔"，章节 B 说"严重障碍"**

<div class="mt-4 text-sm">

| 检测项 | 说明 |
|-------|------|
| **contradictions** | 章节 A vs B 存在张力 |
| **overlaps** | 章节 A 和 C 重复讨论市场 |
| **cross_cutting_themes** | 监管风险影响所有章节 |
| **context_brief** | 给每个 Writer 的上下文提示 |

</div>

<v-click>

<div class="mt-6">

- 让 Writer 写每章时感知其他章节上下文 → **内在一致**的报告
- **容错**：失败时跳过，不阻塞写作（锦上添花 > 硬性依赖）

</div>

</v-click>

---

# Stage 4: Report Writing（写 → 批 → 改）

<div class="grid grid-cols-3 gap-4 mt-4 text-center text-sm">

<div class="bg-blue-50 dark:bg-blue-900 rounded-lg p-4">

### Step 1: Write
Writer LLM 生成 Markdown

`[source:S001]` 引用格式

验证尾行完整性

</div>

<div class="bg-yellow-50 dark:bg-yellow-900 rounded-lg p-4">

### Step 2: Critique
Verifier LLM 独立打分

结构 / 深度 / 证据 / 连贯

1-10 分

</div>

<div class="bg-green-50 dark:bg-green-900 rounded-lg p-4">

### Step 3: Revise
分数 < 8 → 触发修改

Writer 根据批评改

失败则保留原版

</div>

</div>

<v-clicks>

<div class="mt-4 text-sm">

- **为什么独立 Verifier？** Writer 自我评价有"自我肯定偏差"
- **为什么阈值 8？** 过度修改反而引入问题，只改"明显需要改进"的

</div>

</v-clicks>

---

# Writing: 报告组装

<div class="text-sm">

| 部分 | 生成方式 |
|------|---------|
| **标题** | LLM 生成（全局视角） |
| **Executive Summary** | 单独 LLM 调用，跨章节提炼要点 |
| **章节 1-N** | 写-批-改 循环产出 |
| **Conclusion** | LLM 生成 |
| **Sources Used** | 自动提取 `[source:S0xx]` 引用 |
| **Queried But Not Used** | 检索到但未引用 → 可审计性 |

</div>

<v-click>

<div class="mt-4">

> "未引用来源"也列出 → 读者可判断系统是否遗漏重要信息

</div>

</v-click>

---

# Stage 5: Audit（审计）

**全局视角的最终质检**

<div class="text-sm mt-2">

| 检查维度 | 示例 |
|---------|------|
| 无支撑论断 | Conclusion 中论断没带引用 |
| 弱引用 | 某段落只引用了 1 个来源 |
| 缺失内容 | must_cover 要点未出现 |
| 章节不一致 | A 和 B 的数据矛盾 |

</div>

<v-click>

<div class="mt-4">

- 输出 `severity: high/medium/low` + `suggested_fix`
- 当前版本**仅报告问题，不自动修复**（为未来留接口）

</div>

</v-click>

---

# 容错设计：永远能产出

<div class="text-sm">

| 阶段 | 失败场景 | Fallback |
|------|---------|----------|
| Planning | LLM 超时 | 通用 4 章节模板 |
| Research | LLM 分析失败 | 启发式 findings |
| Research | 搜索零结果 | 查询变体（最多 3 种） |
| Synthesis | LLM 失败 | 跳过 |
| Writing | 截断/失败 | 验证→重试→结构化草稿 |
| Audit | Verifier 失败 | 记录通用问题 |

</div>

<v-click>

<div class="mt-6 text-center">

> **宁可输出一份"够用"的报告，也不因某个环节失败而崩溃**

</div>

</v-click>

---

# 模型角色分工

<div class="text-sm mt-4">

| 角色 | 职责 | 温度 | 备注 |
|------|------|------|------|
| **Planner** | 设计研究计划 | 0.2 | 需要创造性但不能太发散 |
| **Researcher** | 分析证据、提炼论点 | 0.2 | 结构化 JSON 输出 |
| **Writer** | 撰写报告章节 | 0.2 | 文本模式，Markdown |
| **Verifier** | 审查 / 批评 / 审计 | **0.0** | 严格客观 |
| **Fast** | 轻量任务 | 0.1 | 省钱省时间 |

</div>

<v-click>

<div class="mt-4">

- 多模型 + 自动 fallback：claude-4.6-sonnet → gpt-5 → sonar-pro
- **Researcher 优先用 sonar-pro**（搜索增强 LLM，天然带引用）+ JSON 适配器
- HAI Proxy (`localhost:6655`) 统一调用，16 RPM 限流

</div>

</v-click>

---

# 检查点与输出

<div class="text-sm">

```
runs/{run_id}/
├── report.md                  # 最终报告
├── plan.md / plan.json        # 研究计划
├── trace.html                 # 交互式执行追踪
├── checkpoints/
│   ├── planned.json           # ← --resume
│   ├── round-1.json
│   └── final.json
├── sources/                   # 原始 HTML + 提取文本
├── artifacts/                 # 章节 MD / 综合结果
└── events.jsonl               # 结构化日志
```

</div>

<v-click>

<div class="mt-2">

`--resume checkpoints/round-1.json` → 跳过已完成的阶段

</div>

</v-click>

---

# 运行示例

```bash
# 基本用法
DEEP_RESEARCHER_API_KEY=<key> uv run python -m deep_researcher \
  --question "煤化工替代石油化工的可行性分析"

# 从文件加载
--question-file queries.json --query-index 1

# 带本地证据
--workspace-source ./internal-reports/

# 只看规划 / 从检查点恢复
--plan-only
--resume runs/.../checkpoints/round-1.json
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
- Tables & Comparisons
- Paragraph Quality
- Summary & Conclusion
- Completeness
- **Intellectual Honesty**（新增）

</div>
</div>

<v-click>

```bash
uv run python evaluate.py runs/<id>/report.md --no-llm  # 仅结构指标
uv run python evaluate.py runs/<id>/report.md            # 完整评估
```

</v-click>

---
layout: center
class: text-center
---

# 关键设计总结

<div class="grid grid-cols-2 gap-6 text-left mt-6">
<div>

🗺️ **先规划再研究** — 带着地图找路

🔄 **迭代加深** — 越查越深，不是盲目重复

🧩 **研究与写作分离** — 结构化数据 → 高质量散文

⚖️ **多层质控** — Gap Review + Critique + Audit

</div>
<div>

🛡️ **处处容错** — 永远能产出

🔗 **链接跟踪** — 顺藤摸瓜找高价值来源

📊 **可信度评分** — 区分 arxiv 和 reddit

🔍 **可审计** — 未引用来源也记录在案

</div>
</div>

---
layout: center
class: text-center
---

# 新功能：Depth Mode（深度推理模式）

**从广度搜索到深度思考**

---

# 为什么需要 Depth Mode？

<div class="grid grid-cols-2 gap-8 mt-8">
<div>

### Breadth（已有）

- 适合 "Map the landscape of X"
- 搜索驱动：5-6 章节 × 多轮搜索
- 输出：**多章节调查报告**
- 强项：覆盖面广、来源丰富

</div>
<div>

### Depth（新增）

- 适合 "Solve this hard problem"
- 推理驱动：分解 → 思考 → 验证 → 修正
- 输出：**深度分析 + 公式推导**
- 强项：逻辑严密、多情景分析

</div>
</div>

<v-click>

<div class="mt-4 text-center">

> 类比：Google 有 **Deep Research**（广度）和 **DeepThink**（深度），我们也需要两种模式

</div>

</v-click>

---

# Depth Mode 架构

```
Question
    │
    ▼
[1. DECOMPOSE] ── planner LLM
    │  分解为子问题 + 依赖图 + 拓扑排序
    ▼
[2. THINK LOOP] ── 按依赖顺序逐一处理:
    │
    │  ┌→ [REASON] ── thinker LLM (高输出 16K tokens)
    │  │    如需外部事实 → 触发按需搜索
    │  │
    │  ├→ [VERIFY] ── verifier LLM
    │  │    通过 → 标记 "verified"
    │  │    失败 → 进入修正
    │  │
    │  └→ [REVISE] ── thinker + 反馈（最多 3 次）
    │       仍失败 → 记录为 "failed path"
    ▼
[3. SYNTHESIZE] ── 逐章节 + 总览报告
    ▼
[4. AUDIT] ── 验证逻辑一致性、引用真实性
```

---

# Depth vs Breadth: 资源使用

<div class="text-sm mt-4">

| 维度 | Breadth | Depth |
|------|---------|-------|
| LLM 调用次数 | ~30+ (plan + 6 sections × search + gap review + report) | ~15-20 (decompose + think + verify + revise + report) |
| 搜索查询 | 大量（每章节 3-4 轮） | 极少（仅按需搜索） |
| 单次输出长度 | 短（结构化 JSON） | 长（推理链 16K tokens） |
| 用时 | ~15-25 分钟 | ~30-45 分钟 |
| 核心开销 | 搜索 + 网页抓取 | LLM 推理 |

</div>

<v-click>

<div class="mt-4">

> Depth 模式用 **更少但更长** 的 LLM 调用，天然更适合速率限制环境

</div>

</v-click>

---

# 首次测试：煤化工深度分析

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

### 报告内容
- 产品谱系四层分类（A/B/C/D 类）
- 乙烯成本函数推导（含联产品抵扣）
- 煤制烯烃临界油价公式
- 煤价敏感性分析（+100元/吨 → +9$/桶）
- 碳价影响建模
- 被否定的分析路径（4 条）

</div>
</div>

<v-click>

<div class="mt-2">

> Think → Verify → Revise 循环工作良好：模型主动否定了斜率 8.5 的简化模型，修正为 16.54 的联产品抵扣模型

</div>

</v-click>

---

# 关键设计决策

<div class="text-sm mt-4">

| 决策 | 选择 | 原因 |
|------|------|------|
| 架构 | 独立 `DeepThinker` 类 | 不污染已有 breadth 代码，单一职责 |
| 状态 | `DepthState` vs `ResearchState` 并行 | 不同关注点，组合优于继承 |
| 子问题处理 | 顺序（按拓扑序） | V1 简单可靠，并行留给后续优化 |
| 模型选择 | Sonnet-first + 300s 超时 | Opus 复杂推理容易超时 |
| 搜索策略 | 按需最少搜索 | 推理为主，搜索为辅 |
| 引用规则 | 只引已验证来源 | 防止模型对不相关来源编造引用 |

</div>

---
layout: center
class: text-center
---

# Q & A

代码：`deep_researcher/workflow.py`（breadth）| `deep_researcher/depth_workflow.py`（depth）

文档：`docs/architecture.md`

<br>

```bash
# Breadth mode（默认）
DEEP_RESEARCHER_API_KEY=<key> uv run python -m deep_researcher \
  --question "你感兴趣的任何研究问题"

# Depth mode（新增）
DEEP_RESEARCHER_API_KEY=<key> uv run python -m deep_researcher \
  --mode depth --question "需要深度分析的复杂问题"
```
