# Planning Demo

这份文档记录了一次真实的 planning 演示，使用：

- 模型：`anthropic--claude-4.6-sonnet`
- 模式：`--plan-only`
- 输入： [queries.md](queries.md)

## Query 1

问题：阳光电源公司研究

运行结果：

- [plan.md](runs/planning-demo/20260309-102518-993420/plan.md)
- [plan.json](runs/planning-demo/20260309-102518-993420/plan.json)
- [trace.html](runs/planning-demo/20260309-102518-993420/trace.html)

我的判断：

- 这份 plan 质量是高的，已经明显进入“可研究”的状态。
- Claude 正确识别了这不是纯公开资料研究，而是“用户提供财报 + 公开市场信息”的组合任务。
- section 划分也合理：历程、产品线、市场与竞争、财务/ROE、成长与估值框架。
- 这类 query 的下一步重点不是再改 planning，而是接入你说的财报源文件，让研究阶段能按 section 吃进去。

## Query 2

问题：中国/欧洲清洁能源占比提升对储能和产业链的影响

运行结果：

- [plan.md](runs/planning-demo/20260309-102433-019726/plan.md)
- [plan.json](runs/planning-demo/20260309-102433-019726/plan.json)
- [trace.html](runs/planning-demo/20260309-102433-019726/trace.html)

我的判断：

- 这份 plan 结构清晰，已经把“中国需求”“欧洲经验”“受益企业”“电网与电价影响”“绿氢/V2G/工业电气化”等层次拆开了。
- 适合后续做成一篇产业链研究报告。
- 这里最有价值的是它没有只盯储能本身，而是把“清洁能源高占比”的连锁影响扩到了电力市场、氢能、电动车和工业侧。

## Query 3

问题：Deep Research 的进展、原理与生产实践

运行结果：

- [plan.md](runs/planning-demo/20260309-101952-374498/plan.md)
- [plan.json](runs/planning-demo/20260309-101952-374498/plan.json)
- [trace.html](runs/planning-demo/20260309-101952-374498/trace.html)

我的判断：

- 这是三份里最适合作为当前仓库基线 demo 的一份。
- Claude 把问题拆成了：产品概览、OpenAI 技术原理、Gemini/Anthropic 对比、开源复现、技术挑战与实现指南。
- 这个拆法和你当前想自己实现 Deep Research 的目标是对齐的，后续直接可以拿来驱动 section research。

## 这次演示暴露出的工程问题

- 原先 `run_id` 只有秒级精度，并行 planning 时会撞目录。我已经修成了微秒级。
- 原先 `planner.max_output_tokens=1800` 对长 query 会截断 JSON。我已经把默认值提高到 `8000`。
- planning 现在已经可以单独跑并输出 `plan.md / plan.json`，方便先调 planning 再调 research。
- 当前 context window 预算已经和输出上限分离，并按模型画像推断，不再把所有主模型都压成 `128k`。
