# AGENTS

## Scope

这个文件只放仓库级、长期稳定的协作约束。

不要把某个 feature 的实现细节、一次性的方案讨论、实验记录写进这里；这些内容放到 `plan/` 目录。

## Source Of Truth

- 运行环境、网关、代理、限流约束以 [restricts.md](/Users/I561043/SAP/DeepResearcher/restricts.md) 为准。
- 项目用法和对外说明以 [README.md](/Users/I561043/SAP/DeepResearcher/README.md) 为准。
- 稳定的工程文档放在 [docs/](/Users/I561043/SAP/DeepResearcher/docs)。
- feature 级计划、方案比较、阶段性设计记录放在 [plan/](/Users/I561043/SAP/DeepResearcher/plan)。

## Working Rules

- 用 `uv` 管理环境和依赖，不要引入第二套 Python 工作流。
- 不要把真实 API key、token 或其他敏感信息写入仓库。
- 优先保持流程可恢复、可追踪、可调试，不要为了省几步实现牺牲 checkpoint、trace 或中间工件。
- 新增能力时，优先做显式配置和数据驱动，不要把提供商或模型细节零散硬编码在流程里。
- 长流程设计要显式考虑 context budget、阶段摘要和状态裁剪，不要默认依赖“把所有历史都塞回 prompt”。

## Repo Layout

- `deep_researcher/`: 运行时代码。
- `tests/`: 回归测试和最小行为验证。
- `docs/`: 稳定文档、使用说明、设计约束。
- `plan/`: feature 计划、临时设计、演示脚本、阶段性 TODO。
- `runs/`: 本地运行产物，不作为长期文档来源。

## Documentation Rules

- `AGENTS.md` 只保留稳定规则，不记录 feature 细节。
- `docs/` 适合放“当前仍然有效”的说明。
- `plan/` 适合放会演化、会失效、会被替换的内容。
- 如果某项内容从实验方案变成稳定约束，再从 `plan/` 提炼到 `docs/` 或 `AGENTS.md`。

## Change Expectations

- 代码改动应同时考虑运行路径、失败路径和调试路径。
- 涉及模型、路由、上下文预算、日志格式的改动，优先补测试。
- 涉及 CLI、配置项、目录结构的改动，优先同步 README 或 docs。
- 需要更新模型能力时，优先改配置文件或集中注册表，不要散落修改多个条件分支。

## Validation

提交前至少做与改动范围匹配的验证：

- Python 测试：`uv run python -m unittest discover -s tests`
- 如果改了 planning/research 流程，至少跑一次最小 `--plan-only` 或 mock workflow
- 如果改了 trace / artifacts / resume，确认 `runs/<run_id>/` 中的关键工件仍然生成
