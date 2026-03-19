# GDR Reasoning Adaptation

## Why

现有流程的 section 输出以 `summary + findings + open_questions` 为主，适合保真，但不够“会推理”。
GDR 的强项不是单纯更长，而是它会持续显式表达：

- 当前核心判断是什么
- 这个判断背后的驱动逻辑是什么
- 证据支持到哪一步，哪些地方仍是推断
- 下一步要验证什么

这些内容如果只停留在模型临场发挥，很难稳定复现，也不利于 debug。

## What We Borrow

- `thesis`: 每个 section 的当前最佳判断
- `key_drivers`: 支撑判断的 2-6 个核心驱动因子
- `reasoning_steps`: 用 `observation -> inference -> implication` 明确把证据和判断连起来
- `counterpoints`: 显式记录反例、张力和证据不足之处
- `analysis artifacts`: 每轮 section synthesis 落独立分析工件，便于看中间推理是否跑偏

## What We Do Not Copy

- 不把第一人称自述式“我正在研究/接下来我要...”直接塞进最终报告
- 不保存或暴露冗长的隐式 chain-of-thought
- 不把一次性的研究内容写进稳定文档

## Expected Effect

- report writer 不再只拿 facts 拼接，而是拿到可用的分析骨架
- gap review 能更容易识别“证据不够”与“推理不够”的差异
- fallback report 也会保留判断、驱动和反证，不至于退化成事实堆砌
