# DeepResearcher AutoResearch 实验报告

## 目标

通过自动化实验循环，优化 DeepResearcher 生成的研究报告质量，使其逼近 Gemini Deep Research 的水平。评估维度包括：结构、段落深度、推理质量、叙事连贯性、引用密度、表格使用、摘要丰富度。

## 方法

- **分支**: `research/mar19`
- **修改范围**: 仅 `prompts.py`（提示词）和 `config.py`（参数配置）
- **测试query**: Query 1（Deep Research 技术进展与原理）
- **评估**: `evaluate.py --no-llm` 的复合分数（composite score）
- 共进行 **9 轮实验**，其中 6 轮保留、3 轮回退

## 实验进程与结果

| 实验 | 分数 | 状态 | 主要改动 | 关键指标 |
|------|------|------|---------|---------|
| baseline | **45.4** | keep | 无修改 | 13K字, 61引用, 15源, 0表格 |
| exp1 | **73.6** | keep | 更深章节、更丰富概述、更多搜索 | 31K字, 161引用, 28源, 5表格 |
| exp2 | **76.9** | keep | 强制表格、更长段落、更多查询 | 34K字, 174引用, 24源, 7表格 |
| exp3 | **78.7** | keep | 8源/节、5-10句段落 | 44K字, 236引用, 42源, 7表格 |
| exp4 | 76.5 | discard | 4查询/节、多样引用 | unique_sources 反而下降 |
| exp5 | 78.0 | discard | 6节、2-3子节 | h2=11 过多 |
| exp6 | **81.1** | keep | 3轮搜索、1-2子节、不强制表格 | 37K字, 131引用, 37源, 53段(理想) |
| exp7 | 73.7 | discard | 严格5-6节、无子节、4轮上限 | 源数暴降25, h3=0 矫枉过正 |
| exp8 | **83.7** | keep | 5-6节、3-4多样查询、gap review关注源多样性 | 33K字, 131引用, 33源, 50段 |
| exp9 | **86.0** | keep | 8结果/查询、引用多样源指令 | 25K字(理想!), 151引用, 32源 |

## 分数趋势

```
baseline  ████░░░░░░░░░░░░░░░░  45.4
exp1      ███████████████░░░░░░  73.6  (+28.2)
exp2      ████████████████░░░░░  76.9  (+3.3)
exp3      ████████████████░░░░░  78.7  (+1.8)
exp6      █████████████████░░░░  81.1  (+2.4)
exp8      █████████████████░░░░  83.7  (+2.6)
exp9      ██████████████████░░░  86.0  (+2.3)   ← 最终最佳
```

**总提升: 45.4 → 86.0 (+89.4%)**

## 关键发现

### 1. 最大单次提升来自 exp1（+28.2 分）

增加章节深度、丰富概述、扩大搜索范围和引入表格，效果最为显著。

### 2. 有效的改动模式

| 改动类别 | 具体变化 | 效果 |
|---------|---------|------|
| **搜索扩容** | results/query: 4→8, sources/section: 3→8, chars/source: 2200→4000 | 信息量翻倍 |
| **迭代深度** | rounds: 2→3 | 更多补充搜索机会 |
| **写作质量** | 段落要求5-8句，分析性论证，机制层推理 | 段落质量提升 |
| **摘要升级** | bullets → 2-3段落式摘要 | 叙事更完整 |
| **源多样性** | gap review 聚焦源多样性，follow_up 强调不同角度 | 引用广度提升 |

### 3. 失败教训

- **exp4**: 增加查询数但未强调多样性 → 同质化搜索，unique_sources 下降
- **exp5**: h2 数量过多 → 结构散乱
- **exp7**: 矫枉过正（强制无子节、限制轮次）→ 内容和结构同时退步

### 4. 最优配置（exp9，当前 HEAD）

```python
# config.py 关键参数
max_rounds = 3              # 从2提升
max_sections = 7            # 从5提升
max_queries_per_section = 3 # 从2提升
max_results_per_query = 8   # 从4翻倍
max_sources_per_section = 8 # 从3大幅提升
max_chars_per_source = 4000 # 从2200提升
writer.max_output_tokens = 12000  # 从8000提升
researcher.max_output_tokens = 5000  # 从3600提升
```

## Prompt 改动总结

### prompts.py 关键变更

1. **Planning prompt**: 增加 section count 指导（5-6节）、查询多样性要求（3-4 diverse queries/section）
2. **Researcher prompt**: 扩大 key_drivers/reasoning_steps/follow_up_queries 上限，新增激进的 follow_up 生成指令，强调不同源类型和角度
3. **Gap review prompt**: 新增源多样性聚焦逻辑 — 若某节仅依赖2-3个源则生成补充查询；仅在关键证据缺失时才生成 gap_tasks
4. **Section writer prompt**: 从"4-8 short paragraphs"升级为"5-8 substantial paragraphs, 5-8 sentences each"，要求机制层推理、observation→inference→implication 链、引用多样源
5. **Overview prompt**: 从 bullets 升级为 2-3 段落式 executive summary 和 conclusion

## 结论

通过 9 轮自动化实验，DeepResearcher 的报告质量分数从 **45.4 提升到 86.0**，几乎翻倍。核心经验：

1. **信息供给是瓶颈** — 搜索数量和源容量的扩容带来最大增益
2. **写作提示要具体** — "5-8句、分析性论证"比"详细描述"有效得多
3. **多样性胜过数量** — exp4 证明了盲目增加查询不如强调不同角度
4. **迭代搜索有收益但有上限** — 3轮是甜区，4轮反而过度
5. **子结构要克制** — 适度的 h3 子节（1-2个/节）比极端方案好
