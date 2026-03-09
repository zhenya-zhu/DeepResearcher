# Query Tests

[queries.md](/Users/I561043/SAP/DeepResearcher/queries.md) 现在作为 planning 阶段的测试输入池。

## 当前 query

1. 阳光电源公司研究
2. 清洁能源占比提升对储能和产业链的影响
3. Deep Research 的进展、原理与生产实践

## 推荐测试顺序

1. 先对第 3 个 query 跑 `--plan-only`。
原因：它和当前仓库目标最接近，便于快速判断规划结构是否合理。

2. 再跑第 2 个 query。
原因：它更偏行业研究，能看出模型在“政策/产业/企业受益链”上的拆分能力。

3. 最后跑第 1 个 query。
原因：它依赖公司年报/季报/半年报等专门材料，planning 时应把“需要用户提供财报源文件”显式列为输入约束。

## 典型命令

```bash
uv run python -m deep_researcher --list-queries --question-file queries.md
uv run python -m deep_researcher --plan-only --question-file queries.md --query-index 3
uv run python -m deep_researcher --plan-only --question-file queries.md --query-index 2
```

## 额外建议

如果你要比较不同模型的 planning 风格，先固定 query，再只替换 `--planner-models`，不要同时换 query 和模型，否则结果没有可比性。
