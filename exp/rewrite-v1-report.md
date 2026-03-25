# DeepResearcher Rewrite v1 实验报告

## 背景

在 exp1-exp9 的 prompt-only 优化（仅改 `prompts.py` + `config.py`）将分数从 45.4 提升到 86.0 后，遇到了天花板。诊断发现两个根本原因：

1. **评估器长度惩罚 bug** — 旧 `evaluate.py` 对超长报告施加了不合理的线性惩罚
2. **workflow.py 被锁定** — auto research 只允许改 prompt 和 config，无法改核心流程

解决方案：解锁 `workflow.py`，从 prompt 调参切换到**架构级重写**。

## 方法

- **分支**: `main`（从 exp9 `d0b2478` 继续）
- **修改范围**: 全部代码（`workflow.py` +809/-120 行, `prompts.py` +209 行, `tracing.py` +234 行, `evaluate.py` +461/-55 行）
- **测试 queries**: 3 个（Deep Research 原理、煤化工替代、FICC 框架）
- **评估**: 重写后的 `evaluate.py`（structural 70% + semantic 30%，`--no-llm` 模式）
- 共进行 **6 轮 query-1 迭代**开发

## 新增核心功能（9 项）

| # | 功能 | 文件 | 作用 |
|---|------|------|------|
| 1 | **结构化推理** | workflow.py | 每轮搜索输出 thesis/key_drivers/reasoning_steps/findings，跨轮增量合并 |
| 2 | **Critique-Revise 循环** | workflow.py, prompts.py | Verifier 打分（1-10），< 8 分触发 Writer 修订 |
| 3 | **跨章节综合** | workflow.py, prompts.py | 检测矛盾、冗余、交叉主题，生成 per-section context briefs |
| 4 | **链接跟踪** | workflow.py | credibility ≥ 0.8 的源自动爬取外链，每节最多 3 个 |
| 5 | **策略查询** | workflow.py | 根据 evidence_requirements 注入 `site:` 前缀查询（arxiv/github/官方文档）|
| 6 | **搜索查询变体** | workflow.py | 每个 query 生成 compact/no-year/subject-focused 3 种变体，按序尝试 |
| 7 | **Section Markdown 验证** | workflow.py | 检测截断、未闭合括号，失败重试 |
| 8 | **报告完整性验证** | workflow.py | 验证所有 section 出现在报告中，末尾不悬挂，失败 fallback |
| 9 | **源可信度评分** | workflow.py | 域名信誉启发式（arxiv=0.9, reddit=0.4 等），影响链接跟踪和引用权重 |

## 其他重要改动

- **并行 section 研究**: `ThreadPoolExecutor(max_workers=3)` + `IntervalRateLimiter` 适配 16 RPM HAI proxy
- **Gap review 增强**: 结构化 gap_tasks（action=workspace|search|derive），sufficiency < 3.5 强制继续
- **Workspace 证据收集**: 本地文件 BM25 评分注入（`--workspace-source`）
- **评估框架重写**: structural（25%）+ semantic coverage（15%）+ LLM judge 8 维度（60%）
- **HTML Trace Viewer**: 交互式 trace.html，可折叠事件时间线
- **审计 prompt**: 全报告审查（unsupported claims、weak citations、missing sections）
- **新增 `fast` 模型角色**: haiku/gpt-5-mini 用于轻量任务

## Query-1 迭代开发记录

| 运行 | 分数 | 特征 | 备注 |
|------|------|------|------|
| 20260322-101931 | **62.2** | 第一版，仅 1 轮搜索 | 功能初版，很多 bug |
| 20260322-111333 | **65.6** | 多轮搜索开始工作 | h2=10, h3=21 |
| 20260322-124447 | **74.2** | Cross-section synthesis 上线 | h2=11, h3=43（子节过多）|
| 20260322-133104 | **72.7** | Critique-revise 上线 | 审计发现幻觉引用问题 |
| 20260322-141844 | **69.5** | 链接跟踪 + 策略查询 | unique_sources 仍低 |
| 20260322-150205 | **77.5** | 查询变体 + markdown 验证 | h2=12, h3=24（结构改善）|

## 多 Query 最终评估

| Query | 运行 | Structural | Semantic | Composite | 主要差距 |
|-------|------|-----------|----------|-----------|---------|
| 1. Deep Research 原理 | 20260322-150205 | 81.6 | 68.0 | **77.5** | unique_sources: 15 vs 53 |
| 2. 煤化工替代 | 20260323-081124 | 100.0 | 60.0 | **88.0** | — |
| 3. FICC 框架 | 20260323-082128 | 86.3 | 55.3 | **77.0** | tables: 0 vs 2 |
| **聚合** | | | | **80.8** | |

## 与 exp9 对比

```
exp9 (prompt-only)    ██████████████████░░  86.0  (Query 1 only, old evaluator)
rewrite-v1 (Query 1)  ████████████████░░░░  77.5  (new evaluator, stricter)
rewrite-v1 (3-query)  █████████████████░░░  80.8  (aggregate, new evaluator)
```

**注意**: 分数不可直接对比。rewrite-v1 使用了完全重写的评估器：
- 移除了旧评估器的长度惩罚 bug（之前短报告反而得高分）
- 新增 semantic coverage 维度（关键词覆盖率），对信息完整性要求更高
- structural 评分逻辑从"接近 reference = 好"改为"more is better"
- 三个不同领域的 query 平均分更能反映泛化能力

## 关键发现

### 1. 架构变更带来的质量提升是结构性的

Critique-revise 循环和跨章节综合让报告内部一致性大幅提升。审计日志显示能捕获幻觉引用（phantom citations）和未支持断言（unsupported claims）。

### 2. unique_sources 是当前最大瓶颈

Query 1 只有 15 个独立源 vs reference 的 53 个。搜索查询变体和策略查询有帮助但不够——DuckDuckGo API 的去重和限流是硬约束。

### 3. Semantic coverage 暴露了信息缺口

60-68% 的 semantic coverage 说明报告在关键词层面仍缺少 reference 中 30-40% 的主题覆盖。这不是写作问题，是搜索深度问题。

### 4. 开发迭代中的非单调进步

Query-1 的 6 轮迭代中分数并非单调递增（74.2 → 72.7 → 69.5 → 77.5），说明新功能引入初期可能有 regression，需要调优才能稳定。

### 5. 领域泛化表现良好

煤化工（88.0）和 FICC（77.0）是完全不同领域，无需调参即可产出合理报告，说明框架泛化能力可靠。

## LLM Judge 评估（Claude Opus 4.6，max_chars=120000）

### 维度明细

| 维度 | Q1 Deep Research | Q2 煤化工 | Q3 FICC | 平均 |
|------|:---:|:---:|:---:|:---:|
| Structure & Organization | 5 | 7 | 6 | 6.0 |
| Depth & Reasoning | 6 | 7 | 7 | 6.7 |
| Evidence & Citations | 2 | 5 | 6 | 4.3 |
| Narrative Coherence | 5 | 6 | 5 | 5.3 |
| Tables & Comparisons | 5 | 7 | 2 | 4.7 |
| Paragraph Quality | 6 | 7 | 6 | 6.3 |
| Executive Summary & Conclusion | 5 | 7 | 5 | 5.7 |
| Completeness | 4 | 6 | 6 | 5.3 |
| **LLM 平均** | **4.75** | **6.5** | **5.38** | **5.54** |

### 完整 Composite 分数（structural 25% + semantic 15% + LLM 60%）

| Query | Structural | Semantic | LLM Judge | **Composite** |
|-------|:---:|:---:|:---:|:---:|
| 1. Deep Research 原理 | 81.6 | 68.0 | 4.75/10 | **59.1** |
| 2. 煤化工替代 | 100.0 | 60.0 | 6.50/10 | **73.8** |
| 3. FICC 框架 | 86.3 | 55.3 | 5.38/10 | **62.1** |
| **聚合** | | | | **65.0** |

### Opus Judge 核心发现

**Q1 — Evidence 仅 2 分（最差）：** 搜索引擎返回了字典定义页和无关页面，未能获取到 Deep Research 的官方文档、API 文档、arXiv 论文和 GitHub 仓库。报告中大量 meta-commentary 承认证据缺失（"evidence gap"），读起来像研究日志而非技术报告。Reference 有 45+ 权威源。

**Q2 — 最佳表现（6.5/10 平均）：** 分析严谨、诚实标注数据置信度，但缺少中文一手数据源（CCTD、中石化报告、券商研报）；价格临界点给出宽泛区间而非精确数字（reference 有 60 USD/bbl 阈值、2000 元/吨极端成本等）。PVC/电石路线完全缺失。

**Q3 — Tables 仅 2 分：** 零表格 vs reference 的收益率曲线对比表、Carry Trade 阶段表等。Section 6 存在严重重复（同一段推理链被复述 3-5 次），暴露了自动生成后缺少去重编辑。缺失逆全球化/结构性通胀的宏观综合章节。

### 对比：--no-llm vs LLM judge

```
--no-llm (structural 70% + semantic 30%)  █████████████████░░░  80.8
LLM judge (struct 25% + sem 15% + LLM 60%)  █████████████░░░░░░░  65.0  (-15.8)
```

LLM judge 的 60% 权重暴露了 structural metrics 掩盖的深层问题：
1. **搜索失败 → 证据空洞**：structural 只看引用数量，LLM 看引用质量和权威性
2. **重复/冗余**：structural 不检测，LLM 直接扣 coherence 分
3. **主题缺失**：semantic coverage 只看关键词重叠，LLM 能发现结构性缺失（如整个子主题未覆盖）

## 待改进方向

1. **搜索质量**（影响 Evidence 维度）：DuckDuckGo 返回字典页/无关页面是 Q1 的根本原因。需引入多搜索引擎（Brave/Bing）、学术搜索（Semantic Scholar）、或 Sonar API
2. **去重与编辑**（影响 Coherence 维度）：Section 内容重复需在 critique-revise 循环中增加去重检查
3. **表格智能触发**（影响 Tables 维度）：FICC 零表格，需根据内容类型（对比、时间序列、阶段划分）自动触发表格生成
4. **中文源获取**（影响 Evidence + Completeness）：煤化工和 FICC 这类中国市场话题需要中文搜索能力
5. **Meta-commentary 清理**（影响 Coherence + Structure）：报告中不应出现 "evidence gap"、"Queried But Not Used" 等工作笔记
6. **Prompt caching**: Anthropic `cache_control` markers 降低 ~30% input token 成本（TODOS.md 中的 P2 项）

## 文件变更清单

| Commit | 描述 | 改动量 |
|--------|------|--------|
| `6a776fe` v1 | exp 报告 + 初始结果 | +537 |
| `586e78c` rewrite plan | 重写计划文档 | +182 |
| `1f30e9e` **核心重写** | 五阶段流水线重构 | +809/-120 |
| `90c7f67` tracing | HTML trace viewer + semantic registry | +234/-24 |
| `0570efd` evaluation | 评估框架扩展 + 新测试 | +461/-55 |
| `b62b805` architecture | 架构文档 | +485 |
| `238191e` samples | 样例报告 + 查询集更新 | +377/-6 |
| `6566a88` slides | Slidev 演示文稿 | +684 |
