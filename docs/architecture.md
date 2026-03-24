# DeepResearcher 架构与运行流程

## 概览

DeepResearcher 是一个**迭代式深度研究代理**，通过多轮搜索-分析-补缺循环，自动生成带引用的长篇研究报告。核心设计理念：**先规划、再迭代研究、最后高质量写作**。

## 运行命令

```bash
DEEP_RESEARCHER_API_KEY=<key> uv run python -m deep_researcher --question-file queries.json --query-index 1
```

### 常用 CLI 选项

| 选项 | 说明 |
|------|------|
| `--question <text>` | 直接指定研究问题 |
| `--question-file <path>` | 从文件加载问题（支持编号列表或 JSON） |
| `--query-index <n>` | 选择文件中第 n 个问题 |
| `--list-queries` | 列出文件中所有问题并退出 |
| `--resume <checkpoint>` | 从检查点恢复 |
| `--plan-only` | 只执行规划阶段 |
| `--max-rounds <n>` | 覆盖研究迭代轮数（默认 3） |
| `--workspace-source <path>` | 添加本地文件作为证据来源 |
| `--planner-models`, `--researcher-models`, `--writer-models`, `--verifier-models` | 覆盖各角色模型 |
| `--mock` / `--mock-llm` / `--mock-tools` | 测试模式 |

## 五阶段流水线

```
┌─────────┐    ┌──────────────────┐    ┌──────────┐    ┌──────────┐    ┌───────┐
│ Planning │ →  │ Iterative Research│ →  │ Synthesis │ →  │  Writing  │ →  │ Audit │
│ (1次LLM) │    │  (最多3轮循环)    │    │ (跨章节)  │    │ (写+批+改)│    │(质检)  │
└─────────┘    └──────────────────┘    └──────────┘    └──────────┘    └───────┘
```

主编排入口：[`DeepResearcher.run()`](../deep_researcher/workflow.py#L612)，按顺序调用 `_plan` → 循环 `_research_section` + `_review_gaps` → `_cross_section_synthesis` → `_write_report` → `_audit_report`。

> **为什么分五阶段？** 核心思路是模拟人类研究员的工作方式：先拟提纲（Planning），然后按提纲搜资料、反复补缺（Iterative Research），写之前先统一口径防止章节打架（Synthesis），再高质量写作并自我审稿（Writing），最后做终审（Audit）。每个阶段有独立的输入/输出边界，便于从任意检查点恢复，也便于单独调试和优化某一阶段。

---

### 1. Planning（规划）

**入口：** [`_plan()`](../deep_researcher/workflow.py#L684)

> **为什么需要规划阶段？** 直接让 LLM 一次性写完研究报告，会导致结构涣散、遗漏重要维度。规划阶段的作用是把一个模糊的研究问题（如"煤化工替代石油化工"）拆解为 5-7 个结构化章节，每个章节带有明确的研究目标和搜索策略。这样后续的搜索和分析就是"带着地图找路"而不是"漫无目的地游荡"。

**流程详解：**

1. **构建 Prompt**：调用 [`build_planning_messages()`](../deep_researcher/prompts.py#L11)，将用户问题、最大章节数、Semantic Registry 的 profile/source_pack 载荷、语义模式传入，生成系统+用户消息。
2. **LLM 调用**：通过 `ModelRouter.complete_json()` 以 Planner 角色发起请求（[workflow.py:695](../deep_researcher/workflow.py#L695)），期望返回 JSON 格式的研究计划。
3. **解析 sections**：遍历返回的 `payload["sections"]`（[workflow.py:698](../deep_researcher/workflow.py#L698)），对每个章节：
   - **查询归一化**：调用 [`_normalized_queries()`](../deep_researcher/workflow.py#L421)，将 LLM 生成的原始查询经过 `_compact_query()` 分词、去停用词、CJK/Latin 分离后压缩为简洁搜索词。
     > **为什么要归一化？** LLM 生成的查询往往过长（如"分析中国煤化工行业替代石油化工的可行性及主要技术路线"），直接丢给搜索引擎会导致召回率极低。归一化后变为"煤化工 替代 石油化工 技术路线"，搜索效果显著提升。同时 CJK/Latin 分离避免了中英混合查询在 DuckDuckGo 上的异常行为。
   - **must_cover 截断**：最多保留 6 条检查点（[workflow.py:712](../deep_researcher/workflow.py#L712)）。
   - **evidence_requirements 解析**：调用 [`_parse_evidence_requirements()`](../deep_researcher/workflow.py#L850) 将原始 dict 转为 `EvidenceRequirement` 对象。
     > **为什么需要 evidence_requirements？** 不同章节对证据的"类型"要求不同——技术章节需要学术论文和官方文档，市场章节需要行业报告和财务数据。通过 `profile_id`（如 `primary_source`、`quantitative_metric`）显式声明需求，后续搜索才能有针对性地去不同类型的来源找证据，而不是所有章节都用一样的通用搜索。
   - 构造 `SectionState` 对象（[workflow.py:713](../deep_researcher/workflow.py#L713)）。
4. **全局元数据提取**：从 payload 中提取 `objective`、`research_brief`、`input_dependencies`、`source_requirements`、`comparison_axes`、`success_criteria`、`risks`（[workflow.py:721-727](../deep_researcher/workflow.py#L721)）。
   > **为什么提取这些全局字段？** 它们为后续所有阶段提供"全局视角"。比如 `comparison_axes` 告诉研究员应该在哪些维度上做对比，`success_criteria` 让 Gap Review 能判断研究是否已经充分，`risks` 提醒写作时需要讨论的风险点。没有这些元数据，各章节容易陷入各自为政、缺少整体一致性。
5. **语义解析（Semantic Resolution）**：对每个章节调用 [`_resolve_section_semantics()`](../deep_researcher/workflow.py#L893)，核心逻辑：
   - 验证 `evidence_requirements` 中的 `profile_id` 是否存在于 Semantic Registry（[workflow.py:900](../deep_researcher/workflow.py#L900)）。
   - 验证 `preferred_source_packs` 是否与 profile 匹配（[workflow.py:903](../deep_researcher/workflow.py#L903)）。
   - 如果 `semantic_mode == "hybrid"` 或无有效 requirements → 展开 Registry 中的查询模板（[workflow.py:954-956](../deep_researcher/workflow.py#L954)），生成 `site:` 前缀查询等。
   - 无有效 requirements 时，触发 [`_minimal_fallback_requirements()`](../deep_researcher/workflow.py#L829) 根据关键词匹配自动推断 profile（如文本含"论文"→ academic profile）。
   - 输出解析结果到 `state/semantic-resolution-{section_id}-{stage}.json`。
   > **为什么需要 Semantic Registry？** LLM 说"需要学术论文"时，系统需要知道具体去哪搜。Semantic Registry 就是这个翻译层——把"需要学术论文"翻译为 `site:arxiv.org`、`site:scholar.google.com` 等具体搜索策略。Hybrid 模式下系统同时使用 LLM 的判断和 Registry 的模板，兼顾灵活性和可靠性。
6. **Fallback**：若 LLM 调用失败，使用 [`_fallback_sections()`](../deep_researcher/workflow.py#L766) 生成 4 个通用章节（Context/Landscape/Risks/Recommendation）。
   > **为什么需要 Fallback？** 规划阶段调用 LLM 可能因网络超时、模型限流等原因失败。通用 4 章节模板确保系统即使在规划失败时也能继续运行，产出一份"够用"的报告，而不是直接崩溃。
7. **检查点与输出**：设置 `state.status = "planned"`，写入 `planned.json` checkpoint、`plan.md`、`plan.json`（[workflow.py:755-764](../deep_researcher/workflow.py#L755)）。

**输出文件：** `plan.md`, `plan.json`, `semantic-resolution-*.json`, `planner-evidence-requirements.json`

---

### 2. Iterative Research（迭代研究，最多 3 轮）

**入口：** [`run()` 中的 while 循环](../deep_researcher/workflow.py#L626)，每轮调用 [`_research_section()`](../deep_researcher/workflow.py#L1098) + [`_review_gaps()`](../deep_researcher/workflow.py#L1358)。

> **为什么要迭代而不是一次搜完？** 一次搜索很难覆盖所有需要的证据——第一轮搜索的结果往往会揭示新的问题和方向（比如搜"煤化工技术"时发现了"费托合成"这个关键词，第二轮就能针对性地搜索费托合成的技术细节）。迭代机制模拟了人类研究员"越查越深"的过程：每轮结束后由 Verifier 评估哪里还有缺口，然后有针对性地补充，而不是盲目重复搜索。

#### 2a. 章节研究（_research_section）

每轮对**所有 pending 章节并行执行**（[`ThreadPoolExecutor`](../deep_researcher/workflow.py#L632)，最多 3 workers）。

> **为什么并行？** 章节之间的研究相互独立（各搜各的），串行执行会浪费大量等待网络 I/O 的时间。3 workers 是 API 限流和搜索引擎反爬之间的平衡点。

每个章节的研究流程：

**Step 1 — 本地证据收集**（[workflow.py:1108](../deep_researcher/workflow.py#L1108)）
- 调用 [`_collect_workspace_evidence()`](../deep_researcher/workflow.py#L1933) → [`_load_workspace_documents()`](../deep_researcher/workflow.py#L1900)
- 底层使用 [`discover_workspace_documents()`](../deep_researcher/workspace_sources.py) 扫描配置的本地路径
- 调用 [`select_workspace_evidence()`](../deep_researcher/workspace_sources.py) 对文档做 BM25 评分，选取与章节最相关的片段
- 每个选中文档注册为 `SourceRecord`（`fetch_status = "workspace"`）

> **为什么先收集本地证据？** 用户可能已有内部报告、技术文档等不在公网上的材料（通过 `--workspace-source` 指定）。这些内部资料往往比网上搜到的信息更可靠、更贴合用户需求，优先纳入可以提高报告的针对性和质量。放在最前面也确保本地证据在 Web 来源之前被注册，避免被源数量上限挤出。

**Step 2 — 查询准备**（[workflow.py:1111-1122](../deep_researcher/workflow.py#L1111)）
- 对章节的 `queries` 做归一化处理
- 调用 [`_strategy_queries()`](../deep_researcher/workflow.py#L467) 根据 `evidence_requirements` 和 `goal` 中的关键词，自动注入策略查询（如 `site:arxiv.org <query>`、`site:github.com <query>`）
- 计算查询预算：`min(查询数, max_queries_per_section + 4)`

> **为什么需要策略查询？** 通用搜索（如 DuckDuckGo）的结果往往偏向新闻和博客。对于需要学术论文或官方文档的章节，仅靠通用搜索很难触达 arxiv、GitHub 等专业来源。策略查询通过 `site:` 前缀强制搜索特定域名，显著提高关键来源类型的命中率。

**Step 3 — 搜索与抓取循环**（[workflow.py:1123-1212](../deep_researcher/workflow.py#L1123)）

对每条查询：

1. **生成搜索变体**：调用 [`_search_query_variants()`](../deep_researcher/workflow.py#L435)，为每条原始查询生成最多 3 个变体：
   - 紧凑版（`_compact_query`）：去停用词、去泛化中文词块
   - 去年份版：移除年份 chunk，避免搜索结果过窄
   - 主题聚焦版：`subject + section_title` 组合

   > **为什么生成变体？** 搜索引擎对查询措辞高度敏感。同一个意图，"煤化工 2024 技术路线"可能返回 0 条结果，而"煤化工 技术路线"返回大量结果。变体机制让系统自动尝试多种表达方式，首次命中即停，既提高了召回率，又避免了不必要的 API 调用。

2. **DuckDuckGo 搜索**：逐个尝试变体，首次有结果即停（[workflow.py:1126-1157](../deep_researcher/workflow.py#L1126)）。搜索由 [`DDGRSearcher`](../deep_researcher/search.py) 执行，每查询最多 `max_results_per_query` 条结果（默认 8）。
3. **URL 抓取与提取**（[workflow.py:1160-1210](../deep_researcher/workflow.py#L1160)）：
   - 调用 [`URLFetcher.fetch()`](../deep_researcher/search.py) 下载页面 HTML
   - 调用 [`extract_relevant_passages()`](../deep_researcher/search.py) 按查询关键词从文本中提取相关段落（最多 `max_chars_per_source` 字符）
     > **为什么不把整个页面传给 LLM？** 一个网页可能有几十 KB 的文本，其中大部分是导航栏、页脚、广告等无关内容。直接传入会浪费 LLM token 预算且引入噪声。`extract_relevant_passages()` 按查询关键词精准截取相关段落，让 LLM 只看真正有价值的内容。
   - 保存 `S001.raw.html` 和 `S001.txt` 到 `sources/` 目录
   - 调用 [`_score_source_credibility()`](../deep_researcher/workflow.py#L107) 计算域名可信度分数（0-1），使用硬编码域名表 + TLD 模式匹配
     > **为什么要评分来源可信度？** 并非所有网页的可信度相同——arxiv.org 的论文和某个匿名博客的帖子不应被同等对待。可信度分数在两个地方发挥作用：(1) 链接跟踪阶段只从高可信度来源出发追踪外链；(2) 为后续写作阶段提供参考，鼓励优先引用高质量来源。
   - 注册为 `SourceRecord`（[`_register_source()`](../deep_researcher/workflow.py#L1883)），URL 去重（同 URL 不重复注册）
4. **源数量控制**：达到 `max_sources_per_section`（Web 来源上限）或总证据上限时提前终止
   > **为什么限制源数量？** 更多来源意味着更多 LLM token 消耗和更长的处理时间。实践发现，每个章节 10-15 个高质量来源通常已足够支撑分析，过多来源反而引入冗余信息，降低 LLM 的分析聚焦度。

**Step 4 — 链接跟踪（Link Following）**（[workflow.py:1214-1282](../deep_researcher/workflow.py#L1214)）
- 仅当证据未满时执行
- 遍历已收集的证据包，筛选 **可信度 ≥ 0.8** 且有原始 HTML 的来源（[workflow.py:1223](../deep_researcher/workflow.py#L1223)）
- 调用 [`_extract_outbound_links()`](../deep_researcher/workflow.py#L40) 从 HTML 中提取外链（过滤同域、登录页、PDF 等）
- 对外链执行 fetch → 提取段落 → 注册为新来源
- 最多跟踪 **3 条** 外链（[workflow.py:1218](../deep_researcher/workflow.py#L1218)）

> **为什么做链接跟踪？** 高质量页面（如 Google AI Blog、Nature 综述文章）通常会链接到其他重要资源（原始论文、技术文档、数据集页面）。这些资源往往不会直接出现在搜索结果中，但正是通过"顺藤摸瓜"才能发现的高价值来源。限制为 3 条是为了控制抓取时间和避免过度爬取。只从可信度 ≥ 0.8 的来源出发，确保追踪的起点本身就可靠，避免从低质量站点跟到更多低质量站点。

**Step 5 — Researcher LLM 分析**（[workflow.py:1290-1356](../deep_researcher/workflow.py#L1290)）
- 调用 [`build_section_research_messages()`](../deep_researcher/prompts.py) 构建 Prompt，包含问题、章节元数据、所有证据包
- Researcher 角色 LLM 返回 JSON，包含：
  - `thesis` — 章节核心判断
  - `key_drivers` — 驱动因素列表（最多 6 条）
  - `reasoning_steps` — 推理链（observation → inference → implication + source_ids），通过 [`_merge_reasoning_steps()`](../deep_researcher/workflow.py#L2106) 去重合并
  - `findings` — 发现列表（claim + source_ids），通过 [`_merge_findings()`](../deep_researcher/workflow.py#L2131) 去重合并
  - `counterpoints` — 反面论点
  - `open_questions` — 未解决问题
  - `follow_up_queries` — 下一轮查询建议
  - `status` — `"draft_ready"` 或 `"continue_research"`

> **为什么要求结构化输出而不是直接写文章？** 这是"研究"和"写作"分离的关键设计。研究阶段输出的是结构化的分析数据（thesis、reasoning_steps、findings），而非散文。好处有三：(1) 多轮研究可以通过 `_merge_findings()` 增量合并，不会因为新一轮的结果覆盖旧发现；(2) Gap Review 可以精准评估每个发现是否有充分引用，而不是去理解散文语义；(3) 写作阶段拿到的是"经过验证的结构化素材"，写出的文章自然更有逻辑和证据支撑。

- 生成章节草稿 [`_section_draft()`](../deep_researcher/workflow.py#L2144) 和推理笔记 [`_section_reasoning_note()`](../deep_researcher/workflow.py#L2179)
- **Fallback**：LLM 失败时使用启发式 findings（[workflow.py:1333-1351](../deep_researcher/workflow.py#L1333)）
- 写入 checkpoint：`section-{id}-round-{n}.json`

#### 2b. Gap Review（缺口审查）

**入口：** [`_review_gaps()`](../deep_researcher/workflow.py#L1358)，每轮研究结束后调用。

> **为什么需要单独的 Gap Review 阶段？** 如果没有 Gap Review，系统只能"跑满 max_rounds 轮"或"跑完 1 轮就停"，无法根据实际证据充分度动态调整。Gap Review 相当于一个"研究主管"，在每轮结束后审视所有章节的证据质量，精准指出哪里还不够（而不是盲目重复所有搜索），并生成有针对性的补充任务。这让系统能自适应地决定何时停止——证据已充分就提前结束节省资源，证据不足就追加定向搜索。

1. **提前终止检查**：若已达 `max_rounds` → 返回 False（[workflow.py:1361](../deep_researcher/workflow.py#L1361)）。
2. **构建 Prompt**：调用 [`build_gap_review_messages()`](../deep_researcher/prompts.py)，将完整 state（含各章节 thesis、findings、open_questions）+ Semantic Registry 载荷传入。
3. **Verifier LLM 调用**（[workflow.py:1371](../deep_researcher/workflow.py#L1371)），返回：
   - `section_sufficiency` — 每章节证据充分度评分（0-5）
   - `global_gaps` — 全局层面的证据缺口
   - `focus_sections` — 需要重点补充的章节 + 原因 + follow_up_queries
   - `gap_tasks` — 结构化缺口任务（含 category/profile_id、priority、follow_up_queries、must_cover）
   - `continue_research` — 是否继续
4. **自适应判断**（[workflow.py:1415-1421](../deep_researcher/workflow.py#L1415)）：
   - LLM 说继续 → 继续
   - 平均 sufficiency < 3.5 → **强制继续**（即使 LLM 说停）
   - 有 gap_tasks → **强制继续**
   > **为什么不完全信任 LLM 的判断？** 实践中发现 Verifier LLM 有时会"过早满足"——在证据明显不足时仍返回 `continue_research: false`。硬编码的 sufficiency < 3.5 阈值作为安全网，确保在客观评分较低时系统不会过早停止。这是"LLM 判断 + 规则兜底"的混合决策模式。
5. **Gap Task 注入**：
   - [`_merge_gap_tasks()`](../deep_researcher/workflow.py#L1015) 合并同 section+category+gap 的任务，高优先级覆盖低优先级
   - [`_apply_gap_tasks()`](../deep_researcher/workflow.py#L1065) 将任务注入对应章节：
     - 添加 `must_cover` 和 `open_questions`
     - 追加新的 `EvidenceRequirement`
     - 合并 `follow_up_queries` 到章节查询队列
     - 将章节状态重置为 `"pending"`（[workflow.py:1090-1091](../deep_researcher/workflow.py#L1090)）
   - 对每个被修改的章节重新执行语义解析（[workflow.py:1096](../deep_researcher/workflow.py#L1096)）
   > **为什么要合并 Gap Tasks？** 多个缺口可能指向同一个方向（如"缺少技术对比数据"和"需要补充性能基准"本质上是同一类需求）。合并避免了下一轮生成重复查询浪费 API 配额。

**检查点：** 每轮结束写入 `round-{n}.json`（[workflow.py:652](../deep_researcher/workflow.py#L652)）

---

### 3. Cross-Section Synthesis（跨章节综合）

**入口：** [`_cross_section_synthesis()`](../deep_researcher/workflow.py#L1443)

> **为什么需要跨章节综合？** 各章节独立研究的最大风险是**信息孤岛**：章节 A 说"该技术前景广阔"，章节 B 说"该技术面临严重监管障碍"，如果直接写入报告会让读者困惑。综合阶段的核心价值是在写作前发现并标注这些矛盾、重叠和交叉主题，让 Writer 在写每个章节时都能意识到其他章节的上下文，从而产出一份**内在一致**的报告而非几篇独立文章的拼凑。

- **前置条件**：至少 2 个章节（[workflow.py:1446](../deep_researcher/workflow.py#L1446)）
- **Prompt**：[`build_cross_section_synthesis_messages()`](../deep_researcher/prompts.py) 将所有章节的 thesis、findings、key_drivers 打包
- **Verifier LLM 返回**（[workflow.py:1450](../deep_researcher/workflow.py#L1450)）：
  - `contradictions` — 章节间矛盾点（如章节 A 说"市场增长"、章节 B 说"需求萎缩"）
  - `overlaps` — 章节间重叠内容（避免报告中重复论述）
  - `cross_cutting_themes` — 跨领域主题（如"监管风险"同时影响技术和市场章节）
  - 每个章节的 `context_brief` — 写作时需注意的交叉关系
- **存储**：写入 `state.cross_section_synthesis`，输出 `artifacts/cross-section-synthesis.json`
- **容错**：失败时跳过，不阻塞后续写作（[workflow.py:1477-1484](../deep_researcher/workflow.py#L1477)）
  > **为什么容错时选择跳过？** 跨章节综合是"锦上添花"——没有它报告仍然可以生成，只是可能存在一些不一致。相比因为综合失败导致整个报告生成中断，跳过是更务实的选择。

---

### 4. Report Writing（报告写作）

**入口：** [`_write_report()`](../deep_researcher/workflow.py#L1486)

> **为什么将写作与研究分离？** 研究阶段产出的是结构化数据（thesis、findings、reasoning_steps），还需要一个专门的写作阶段将这些数据转化为人类可读的连贯文章。分离的好处：(1) 研究数据可以被多次使用（换一种写作风格不需要重新搜索）；(2) 写作阶段可以利用跨章节综合的结果来协调叙事；(3) 批评-修改循环专注于**表达质量**而非信息完整性（后者已被研究阶段保证）。

#### 4a. 章节写作（写 → 批 → 改）

每章节调用 [`_write_report_section()`](../deep_researcher/workflow.py#L1581)，经历三步循环：

**Step 1 — 初始写作**（[workflow.py:1586-1609](../deep_researcher/workflow.py#L1586)）
- 调用 [`build_section_report_messages()`](../deep_researcher/prompts.py) 构建 Prompt，包含：章节研究数据（thesis/findings/reasoning_steps）、跨章节综合上下文、引用格式要求
- Writer LLM 以文本模式返回 Markdown（非 JSON），使用 `complete_text()`
- 经 [`_normalize_section_markdown()`](../deep_researcher/workflow.py#L1776) 确保以 `## 章节标题` 开头
- 经 [`_validate_section_markdown()`](../deep_researcher/workflow.py#L1808) 检查：标题完整、尾行完整（不悬挂）、括号/引号配对
  > **为什么要验证尾行完整性？** LLM 生成长文本时容易在 token 上限处被截断，导致最后一行是半句话或未闭合的括号。这在最终报告中非常刺眼，且会破坏 Markdown 渲染。通过 `_line_ends_cleanly()` 和 `_line_has_unbalanced_tail()` 的组合检查，可以在截断发生时立即触发重试。
- **验证失败时重试**：调用 [`_build_section_report_retry_messages()`](../deep_researcher/workflow.py#L1785)，指示 LLM 缩短篇幅并修正问题

**Step 2 — 批评（Critique）**（[workflow.py:1612-1627](../deep_researcher/workflow.py#L1612)）
- 调用 `build_section_critique_messages()` 构建批评 Prompt
- Verifier LLM 返回 JSON，包含：
  - `issues` — 具体问题列表（结构/深度/证据/连贯性）
  - `overall_quality` — 总体质量分（1-10）

> **为什么用独立的 Verifier 角色来批评？** 让 Writer 自我评价会导致"自我肯定偏差"——LLM 倾向于认为自己写的东西没问题。使用独立的 Verifier 角色（甚至可以是不同模型）模拟了人类编辑流程中"作者-审稿人"的分离，能更客观地发现问题。

**Step 3 — 修改（Revise）**（[workflow.py:1629-1654](../deep_researcher/workflow.py#L1629)）
- 仅当 `quality_score < 8` 且有 `critique_issues` 时触发
- 调用 `build_section_revise_messages()`，将原始 Markdown + 批评结果传给 Writer LLM
- 修改后再次验证，验证失败则保留原始版本
  > **为什么阈值是 8 而不是更高？** 实践中发现 LLM 的修改有时反而会引入新问题（过度修改、丢失原有信息）。阈值 8 意味着只有"明显需要改进"的章节才触发修改，避免了对"已经不错"的章节做不必要的折腾。修改后仍需再次验证也是出于同样的防御性考虑。

**Fallback**：整个写作流程失败时，使用 [`_section_draft()`](../deep_researcher/workflow.py#L2144) 的结构化草稿作为兜底（[workflow.py:1685](../deep_researcher/workflow.py#L1685)）

#### 4b. 报告组装

**概览生成**：[`_generate_report_overview()`](../deep_researcher/workflow.py#L1725)
- 调用 [`build_report_overview_messages()`](../deep_researcher/prompts.py) → Verifier LLM 返回报告标题、Executive Summary（最多 5 条）、Conclusion（最多 4 条）
- 失败时使用 [`_fallback_report_overview()`](../deep_researcher/workflow.py#L1752) 从章节 thesis 拼接
  > **为什么 Executive Summary 由单独的 LLM 调用生成？** 摘要需要从全局视角概括所有章节的核心发现，让读者不看正文也能抓住要点。如果在写各章节时顺便写摘要，LLM 只能看到当前章节的上下文，无法做出跨章节的提炼。

**组装**：[`_assemble_report()`](../deep_researcher/workflow.py#L1700)
- 顺序拼接：标题 → Executive Summary → 各章节 Markdown → Conclusion → Remaining Gaps

**来源附录**：[`_append_source_appendices()`](../deep_researcher/workflow.py#L2049)
- 正则提取报告中所有 `[source:S001]` 引用（[workflow.py:2051](../deep_researcher/workflow.py#L2051)）
- 生成两个附录：
  - **Sources Used As Citations** — 被引用的来源（source_id + 标题 + URL）
  - **Queried But Not Used As Citations** — 检索到但未被引用的来源（含 section_id、raw_query、executed_query）
  > **为什么要列出"未被引用"的来源？** 这是为了可审计性和透明度。读者（或后续的人类研究员）可以通过未引用来源判断：(1) 系统是否遗漏了重要信息（某个高度相关的结果为什么没被引用？）；(2) 搜索策略是否合理（大量不相关的结果说明查询需要优化）。这也是 `evaluate.py` 评估"唯一来源数 vs 引用数"比率的数据基础。

**完整性验证**：[`_validate_report_completeness()`](../deep_researcher/workflow.py#L1837)
- 检查所有章节标题是否出现在报告中
- 检查最后一个章节是否有足够内容（≥ 60 字符）
- 检查报告尾行是否完整（不悬挂、不截断）
- 验证失败时先尝试 [`_fallback_report()`](../deep_researcher/workflow.py#L2212)，再失败则标记 `state.status = "failed"`（[workflow.py:1543](../deep_researcher/workflow.py#L1543)）

**检查点：** `report-generated`

---

### 5. Audit（审计）

**入口：** [`_audit_report()`](../deep_researcher/workflow.py#L1552)

> **为什么在写完后还需要审计？** 写作阶段的批评-修改循环是**逐章节**进行的，无法发现全局性问题（如某个论断在章节 A 有引用支撑、但在 Conclusion 中被无引用地重复；或某个章节 Writer 跳过了 must_cover 中的某个要点）。Audit 是**全局视角**的最终质检，相当于出版前的校对环节。虽然当前版本仅报告问题不自动修复，但 `audit_issues` 为使用者提供了明确的改进方向，也为未来实现自动修复留下了接口。

1. **Prompt**：调用 [`build_audit_messages()`](../deep_researcher/prompts.py) 将完整报告 Markdown + state 传入
2. **Verifier LLM 返回**（[workflow.py:1557](../deep_researcher/workflow.py#L1557)）JSON，包含：
   - `status` — `"pass"` 或 `"fail"`
   - `issues` — 问题列表，每条含：
     - `severity` — `"high"` / `"medium"` / `"low"`
     - `section_title` — 涉及章节
     - `reason` — 问题描述（如"该论断无引用支撑"、"仅引用单一来源"）
     - `suggested_fix` — 修复建议
3. **存储**：写入 `state.audit_issues`（`List[AuditIssue]`）
4. **容错**：失败时记录一条 severity=medium 的通用审计失败问题（[workflow.py:1574-1579](../deep_researcher/workflow.py#L1574)）
5. **注意**：当前审计阶段**仅报告问题，不自动修复**。修复需人工根据 `audit_issues` 判断。

**最终输出**：设置 `state.status = "completed"` → 写入 `report.md` → `final.json` checkpoint → 生成 `trace.html`（[workflow.py:662-667](../deep_researcher/workflow.py#L662)）

## 模型角色分工

| 角色 | 用途 | 默认模型候选 | 温度 |
|------|------|-------------|------|
| Planner | 设计研究计划 | claude-4.6-sonnet, gpt-5, sonar-pro | 0.2 |
| Researcher | 分析证据、提炼论点 | claude-4.6-sonnet, gpt-5, sonar-pro | 0.2 |
| Writer | 撰写报告章节 | claude-4.6-sonnet, gpt-5, opus | 0.2 |
| Verifier | 缺口审查、批评、审计 | claude-4.6-sonnet, gpt-5, sonar-pro | 0.0 |
| Fast | 轻量任务 | claude-4.5-haiku, gpt-5-mini, sonar | 0.1 |

通过 HAI Proxy (`localhost:6655/litellm/v1`) 调用，带速率限制（16 RPM）。

## 核心源文件

| 文件 | 说明 | 大致行数 |
|------|------|---------|
| `deep_researcher/__main__.py` | 入口 | - |
| `deep_researcher/cli.py` | CLI 参数解析 | ~440 |
| `deep_researcher/config.py` | 配置管理（AppConfig） | ~233 |
| `deep_researcher/state.py` | 数据结构（ResearchState, SectionState, SourceRecord） | ~211 |
| `deep_researcher/workflow.py` | 主编排引擎（DeepResearcher 类） | ~2000+ |
| `deep_researcher/prompts.py` | 所有阶段的 LLM Prompt 模板 | ~676 |
| `deep_researcher/llm.py` | LLM 后端实现（OpenAI/Anthropic 兼容） | ~300+ |
| `deep_researcher/search.py` | 网页搜索（DuckDuckGo）与 HTML 抓取 | ~550+ |
| `deep_researcher/semantic_registry.py` | 证据画像与来源包注册表 | ~115 |
| `deep_researcher/tracing.py` | 日志、检查点与 HTML Trace 生成 | ~250+ |
| `deep_researcher/workspace_sources.py` | 本地文件发现与证据选取 | ~250+ |
| `deep_researcher/json_utils.py` | JSON 提取与修复工具 | ~96 |
| `evaluate.py` | 评估框架 | ~400+ |

## 状态管理与检查点

**ResearchState** 是核心状态对象，贯穿全流程并在每个关键节点序列化为 checkpoint：

- `planned.json` → `round-1.json` → `round-2.json` → `final.json`
- 支持 `--resume` 从任意检查点恢复

### 主要数据结构

**ResearchState**（根对象）：
- `run_id` — 唯一标识
- `question` — 研究问题
- `status` — "created" → "planned" → "completed" / "failed"
- `sections: List[SectionState]` — 章节数据
- `sources: Dict[source_id, SourceRecord]` — 所有检索来源
- `report_markdown` — 最终报告
- `audit_issues` — 质量问题
- `cross_section_synthesis` — 跨章节综合结果

**SectionState**（每章节）：
- `section_id`, `title`, `goal`, `queries`
- `must_cover` — 分析检查点
- `evidence_requirements` — 证据需求
- `thesis`, `findings`, `key_drivers`, `reasoning_steps`
- `source_ids` — 引用来源
- `evidence_sufficiency: float` — 充分度评分 (0-5)

**SourceRecord**（每个来源）：
- `source_id` (S001, S002, ...)
- `query`, `title`, `url`, `snippet`, `excerpt`
- `fetch_status` — "unfetched" / "fetched" / "failed"
- `credibility_score` — 域名可信度 (0-1)
- `raw_artifact`, `text_artifact` — 原始文件路径

## 输出目录结构

```
runs/{run_id}/
├── report.md                    # 最终报告
├── plan.md / plan.json          # 研究计划
├── trace.html                   # 交互式执行追踪
├── checkpoints/                 # 状态快照
│   ├── planned.json
│   ├── round-1.json
│   └── final.json
├── sources/                     # 原始 HTML + 提取文本
│   ├── S001.raw.html / S001.txt
│   └── section-id-1.json
├── artifacts/
│   ├── report-sections/         # 各章节 Markdown
│   ├── report-failures/         # 写作失败记录
│   └── cross-section-synthesis.json
├── analysis/                    # 每轮推理笔记
├── state/                       # 语义解析结果
└── events.jsonl                 # 结构化日志
```

## 报告格式

```markdown
# 报告标题

## Executive Summary
- 要点 1
- 要点 2

## 章节 1 标题
正文内容，包含 [source:S001] 引用...

## 章节 2 标题
...

## Conclusion
- 结论 1
- 结论 2

## Remaining Gaps
- 未解决问题 1

## Sources
- S001: [标题](URL)
- S002: [标题](URL)
```

## 评估机制（evaluate.py）

**结构指标**（无需 LLM）：字数、章节数、表格数、引用数、唯一来源数、段落数

**LLM 评分**（需 API）：
- Structure & Organization (0-10)
- Depth & Reasoning (0-10)
- Evidence & Citations (0-10)
- Narrative Coherence (0-10)
- Tables & Comparisons (0-10)
- Paragraph Quality (0-10)
- Executive Summary & Conclusion (0-10)
- Completeness (0-10)

## 环境变量配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEEP_RESEARCHER_API_KEY` | HAI Proxy API Key | - |
| `DEEP_RESEARCHER_BASE_URL` | LiteLLM 端点 | `http://localhost:6655/litellm/v1` |
| `DEEP_RESEARCHER_ANTHROPIC_BASE_URL` | Anthropic 端点 | `http://localhost:6655/anthropic/v1` |
| `DEEP_RESEARCHER_PLANNER_MODELS` | 规划器模型候选（逗号分隔） | 见上表 |
| `DEEP_RESEARCHER_RESEARCHER_MODELS` | 研究员模型候选 | 见上表 |
| `DEEP_RESEARCHER_WRITER_MODELS` | 写作者模型候选 | 见上表 |
| `DEEP_RESEARCHER_VERIFIER_MODELS` | 审核者模型候选 | 见上表 |
| `DEEP_RESEARCHER_WORKSPACE_SOURCES` | 本地证据路径（冒号或换行分隔） | - |

## 关键设计特点

- **迭代加深**：通过 gap detection 发现证据不足 → 生成新查询 → 再次搜索
- **引用多样性**：Prompt 强制要求分散引用，避免过度依赖少数来源
- **多层质控**：Critique/Revise 循环 + 全局 Audit
- **容错回退**：规划失败用通用 4 章节模板、研究失败用启发式发现、写作失败保留草稿
- **并行处理**：章节研究通过 ThreadPoolExecutor 并行（最多 3 workers）
- **多语言查询归一化**：中文停用词去除、CJK/Latin 分词
- **网络模式自动检测**：proxy/direct 自适应，按域名缓存最优模式
- **Semantic Registry**：证据画像 + 来源包机制，将高层需求映射为具体检索策略
