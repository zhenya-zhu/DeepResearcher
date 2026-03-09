> 更新说明：这份文档保留为原始参考稿。针对当前仓库环境、`restricts.md` 约束和多模型/可观测性重构后的方案，请优先查看 [架构评估与优化方案.md](架构评估与优化方案.md)。

# **基于 Claude 模型构建深度研究智能体 (Deep Researcher) 的端到端系统架构与工程实现指南**

随着大型语言模型（Large Language Models, LLMs）基础能力的爆发式增长，人工智能系统的设计范式正在经历一场从被动式对话问答向主动式、长周期、自主执行的智能体（Autonomous Agents）工作流的深刻革命。在这场技术变迁中，“深度研究”（Deep Research）系统已经成为衡量工业级智能体架构能力的“北极星”指标 1。所谓深度研究系统，是指能够处理开放式、高度复杂、需要跨越多个信息源进行长期探索的信息检索与知识合成任务的智能系统。它不仅超越了传统的检索增强生成（Retrieval-Augmented Generation, RAG）范式中单次查询与单次生成的局限，更通过战略规划、动态网络浏览、跨数据源证据聚合、补丁式文件编辑以及迭代推理的自主循环，生成具有极高学术价值和商业价值的引用级研究报告 1。

在当前的工业生产环境中，OpenAI 的 Deep Research、Google 的 Gemini Deep Research 以及 Anthropic 的 Claude Research 已经确立了专有闭源系统的标杆 1。然而，对于意图在数据隐私可控的前提下构建定制化研究基础设施的企业或开发者而言，利用现有的顶级推理模型（如 Anthropic 的 Claude 3.5 Sonnet）并结合开源编排框架从零开始架构此类系统，是一项极具挑战但收益巨大的工程任务。本报告将详尽剖析如何在使用现有 Claude 模型且不进行任何模型微调的前提下，通过极致的架构设计、严谨的多智能体拓扑控制、精细化的状态与记忆管理机制、高阶提示词工程策略、稳健的数据摄取基础设施以及复杂的应用层容错算法，替开发者架构一个具备生产级可用性的 Deep Researcher 项目。

## **第一章：深度研究系统的核心架构范式与拓扑选择**

深度研究智能体本质上是一个集成了动态推理、自适应规划、多轮外部数据检索与工具调用，以及全面分析报告生成能力的复杂分布式计算系统 1。在系统设计层面，其架构分类主要取决于底层大语言模型在任务规划和执行过程中的控制权分配模式。系统在处理多步骤、高不确定性的研究任务时，必须在执行的确定性稳定性与探索的发散性灵活性之间寻找微妙的平衡。

### **架构范式的演进与权衡**

在当前的工程实践中，构建智能体工作流的拓扑结构主要分为单智能体架构（Single-Agent）与多智能体架构（Multi-Agent）。单智能体架构依赖单一的模型实例全权负责整个生命周期的任务规划、工具执行、网络浏览与自我反思 1。例如，某些专有系统（如 Step-DeepResearch）采用了流线型的 ReAct（Reasoning and Acting）风格的单智能体设计，通过极长的上下文窗口（高达 128K 甚至更多）以及在训练阶段将“原子能力”直接内化到模型权重中来实现复杂任务的闭环 2。这种架构的优势在于其维持了对整个任务历史完整且未被分割的记忆，系统内部的逻辑连贯性较强。然而，在不进行模型微调、仅调用现有 API（如 Claude 3.5 Sonnet）的约束条件下，单智能体架构暴露出了致命的缺陷。随着研究任务的深入，模型在试图同时处理来自多个独立检索线程的冗长工具反馈时，极易陷入“上下文冲突”（Context Clash）与“注意力衰退”的困境，导致逻辑混乱、关键信息遗漏以及不可挽回的 Token 耗尽 1。

为了突破单智能体的物理限制，当前生产级深度研究系统的演进趋势强烈倾向于多智能体（Multi-Agent）拓扑结构。多智能体系统通过将一个庞大而复杂的开放式任务分解为多个高度专业化的子任务，并将其委派给在独立上下文窗口中运行的子智能体来解决计算瓶颈 1。这种架构不仅具备卓越的可扩展性与并行处理能力，还能通过严格的状态隔离有效防止主控制节点的上下文窗口膨胀。

| 架构设计维度 | 单智能体架构 (Single-Agent) | 多智能体架构 (Multi-Agent / Supervisor-Worker) |
| :---- | :---- | :---- |
| **核心控制流** | 线性或简单的循环结构，单一模型包揽所有的决策、路由与执行职能，容错率较低 1。 | 树状或复杂图状结构，采用主管节点（Supervisor）负责战略路由，工作节点（Workers）负责具体执行 1。 |
| **上下文管理机制** | 维持单一、连续且极其庞大的上下文历史，对底层模型的长文本长程注意力机制要求极高 1。 | 实施严格的状态隔离。子智能体在纯净的上下文中处理嘈杂的原始数据，并在完成任务后仅向主管返回高度压缩的洞察 1。 |
| **并发与吞吐能力** | 仅能串行处理单一任务序列，在面对需要跨越数百个网页的深度研究任务时耗时极长 1。 | 具备极强的并发能力。主管节点可同时扇出（Fan-out）多个子智能体并发执行异构的检索任务，显著缩短系统响应时间 1。 |
| **调试与定向优化** | 系统呈现高度的“黑盒”特性，开发者难以对特定的子任务（如单纯的网页解析或逻辑反思）进行定向的提示词干预与优化 1。 | 模块化程度极高，系统被清晰解耦。开发者可针对特定节点（如内容撰写者、网络检索者）独立优化提示词、分配专门的工具甚至切换不同参数规模的模型 4。 |

### **基于 LangGraph 的显式状态机编排**

为了在工程上严谨地实现上述多智能体架构，本项目选择采用 LangGraph 框架作为底层的任务编排引擎。LangGraph 是一个建立在 LangChain 生态之上的图论框架，它将智能体工作流显式建模为状态机（State Machines）1。相较于早期那些将智能体视为依赖注入的强类型对象、依靠黑盒魔法进行隐式流转的框架，LangGraph 要求开发者明确定义图的节点（Nodes，代表对 Claude 的大语言模型调用或特定的 Python 计算逻辑）与边（Edges，代表状态转移的条件和控制流）1。

在 LangGraph 的深层实现机制中，图的执行受到图计算领域经典的 Pregel 系统的启发，系统以离散的“超级步”（Super-steps）进行运转 9。在图的执行生命周期开始时，所有的节点处于非活动状态。当一个节点通过任何传入的边（通道）接收到新的状态消息时，它便被激活。在每一个超级步中，多个被激活的节点（例如并行执行检索任务的子智能体）可以同时运行各自的逻辑 9。当这些并行节点完成其操作后，它们不会直接修改全局状态，而是将输出封装为状态增量消息，沿着传出的边发送。在超级步的末尾，LangGraph 引擎收集所有并发生成的消息，利用预先定义好的聚合函数（Reducers）将它们安全地合并到全局状态对象中，随后激活下一批节点 9。这种基于消息传递和超级步同步的机制，完美解决了在多智能体并发调用各种网络爬虫工具时可能引发的竞态条件和状态不一致问题。对于意图构建高可靠性深度研究智能体的团队而言，这种能够精确控制执行顺序、支持多重复杂循环以及随时允许人类介入（Human-in-the-loop）的编排方式具有绝对的优越性 1。

## **第二章：长周期记忆的维系与全局状态管理体系**

在一个典型的深度研究任务中，系统可能需要执行数百次的搜索、阅读数十万字的文档、进行多次深刻的逻辑反思并最终输出上万字的报告。如果仅仅依赖 Claude 模型的原生上下文窗口来承载所有的历史信息，系统将不可避免地陷入上下文坍塌。稳健的 Deep Researcher 架构必须将系统的“记忆”与大语言模型的“计算”进行物理和逻辑上的解耦，构建具有明确功能边界的独立记忆层级 1。

### **Pydantic 与 TypedDict 驱动的状态契约**

在 LangGraph 多智能体网络中，“状态”（State）是系统的灵魂。它是一个贯穿整个图执行生命周期的共享数据结构，所有的节点都从其中读取先验知识，并在完成任务后向其中写入增量更新 9。为了保证这个分布式系统在海量并行任务中的数据一致性与类型安全，系统必须在顶层使用严格的数据验证模型（如 Python 中的 TypedDict 或 Pydantic BaseModel）来定义全局状态契约（Schema）12。

一个为深度研究量身定制的全局状态对象（OverallState）通常需要涵盖极具结构化的维度。首先是对话与指令历史维度，这一部分通常被注解为接收消息列表，系统通过追加机制（Append-only）智能合并来自用户的新指令与模型产生的新交互，从而保留任务的主线脉络 13。其次是累积知识库维度，在并行子智能体各自在互联网上挖掘信息并返回后，系统利用特定的操作符（如 operator.add）将不同分支获取的数据片段、网页链接和结构化摘要无损地拼接到全局知识列表中，确保任何一个微小的证据都不会被覆盖 13。最后是控制论元数据维度，系统需要显式地追踪诸如初始搜索查询的数量、最大允许的研究循环次数、当前已执行的循环迭代次数以及判定研究是否充分的布尔标志 13。通过将节点返回的输出严格限制为仅包含这些状态增量更新的微小 JSON 对象，系统极大地降低了节点间并行数据传输的内存开销，避免了在分支之间不必要地复制动辄上百 KB 的完整对话历史 13。

### **Todo Files：长周期任务的外部化认知外脑**

除了全局的高频状态流转，处理耗时极长的深度研究任务还需要一种持久化的微观任务追踪机制。基于此，本架构引入了“待办事项文件”（Todo Files）机制，将其作为智能体系统的外部化认知外脑 1。Todo Files 的本质是采用显式的结构化 JSON 对象或格式化的 Markdown 文件来精确记录系统在多维解空间中的探索进度 1。

在具体的工程实现中，这不仅是一个抽象的概念，更是真实存储在系统工作目录下的物理文件。推荐采用具有极强规范性的命名约定，例如 {issue\_id}-{status}-{priority}-{description}.md 15。在这些文件的头部，系统会利用 YAML Frontmatter 格式存储关键的结构化元数据，包括任务的当前生命周期状态（从 pending 待处理，到 ready 准备就绪，再到 complete 已完成）、任务优先级、所分配的子智能体名称以及该任务所依赖的其他前置任务 15。而文件的正文部分则包含了标准化的模板内容，如问题陈述、初步发现、提议的解决方案、建议的行动路径以及验收标准和按时间顺序追加的工作日志 15。

引入 Todo Files 机制为大语言模型解决复杂问题带来了不可替代的认知优势。首先，它实现了极限的注意力聚焦。当 Claude 的某个特定子智能体被唤醒执行当前阶段的任务时，它无需将整个数十万字的搜索历史塞入当前的工作记忆中，只需读取对应 Todo File 中定义的“问题陈述”与“下一步行动”即可 1。这种状态隔离极大提升了模型的推理敏锐度。其次，它为系统的主管节点提供了极其清晰的进度审计与依赖管理视图。通过周期性地解析这些文件系统中的 YAML 前缀或 JSON 结构，Supervisor 可以动态构建出一张庞大的有向无环图（DAG），清晰地掌握哪些研究方向已经陷入死胡同、哪些任务由于前置条件未满足而被阻塞 15。最为关键的是，Todo Files 赋予了系统在遭遇上下文崩溃后的无缝恢复能力。当一个深入探索的智能体实例逼近其 200K Tokens 的上下文物理极限，面临幻觉爆发的风险时，系统可以安全地拦截该进程，提取其核心发现并更新到 Todo File 中，随后销毁该实例。接着，系统能够以极其干净、低占用率的新上下文重新实例化一个智能体，无缝加载 Todo File 恢复当前进度，继续推进研究 1。

### **状态压缩机制与知识提纯**

在多智能体网络中，如果底层的子智能体直接将它们抓取到的包含数千个 HTML 标签、杂乱无章的原始网页数据扔给处于核心协调位置的 Supervisor 节点，后者的上下文窗口将在瞬间被击穿崩溃 1。因此，在本项目的架构设计中，必须在工作节点和主管节点之间部署强大的“状态压缩”（State Compression）节点 1。

子智能体在完成外部数据检索并获取海量原始文本后，绝不允许直接向上游返回这些未经清洗的数据。相反，它们必须额外发起一次或多次内部的 Claude API 调用。在这些专门用于压缩的调用中，提示词被严格设定为剔除一切无关字符、广告文本、导航栏代码，仅仅从语料库中提炼出高密度的核心事实、深刻的数据洞察以及高度结构化的来源引用链接 1。这种经过多重过滤和高压浓缩后的纯净数据才被允许汇入前文提到的全局状态对象中。这种递归式的摘要与 Token 截断算法，是防止系统产生信息冗余、维持多智能体网络在长期运行中保持敏捷与稳定的核心架构屏障 1。

## **第三章：多智能体协同机制与动态控制流编排**

明确了底层计算框架与状态存储体系后，设计的核心转向如何优雅地编排不同智能体之间的协作规约。目前的生产级深度研究架构早已摒弃了盲目试错的线性循环，而是采用“规划与解决”（Plan-and-Solve）结合动态反思迭代的复杂工作流 1。在本文构建的架构中，整个深度研究的生命周期被严密地划分为三个层层递进的执行阶段。

### **第一阶段：需求澄清、范围界定与全局大纲生成**

深度研究任务的失败往往源于初始目标的不明确。系统的工作流首先由一个范围界定（Scope）阶段主导 1。当用户输入一个宏大且模糊的研究主题时，系统不会立即启动搜索。相反，它会利用交互式对话节点进行“用户澄清”，识别出请求中缺失的关键上下文或可能存在的歧义 1。当收集到足够的信息后，系统会调用专门的大语言模型节点，将漫长而碎片化的对话历史，通过严格的转换提示词模板，重塑为一份高度结构化且不存在任何歧义的“研究简报”（Research Brief）1。这份简报被注入到不可变的全局状态字典中，作为指引后续所有研究行动的唯一“北极星”标准，并在整个任务的生命周期内接受绝对的遵循 1。

确立了北极星标准后，系统内部的规划器（Planner）智能体会仔细审视这份研究简报，并生成一个详尽、静态的研究疑问大纲 1。与早期那些完全无结构、想到哪里搜到哪里的完全自主智能体相比，强制在行动前生成一张清晰的静态疑问大纲，从根本上消除了智能体在执行过程中无限发散、偏离主题的固有风险 1。大纲中的每一个疑问都对应着一个潜在的独立研究子空间，为后续的并发执行提供了清晰的切分依据。

### **第二阶段：并行扇出、深度挖掘与动态检索微循环**

进入实质性的执行阶段后，系统架构中的 Supervisor 节点正式接管控制权。主管节点读取全局状态中的研究简报与疑问大纲，并触发子研究员图的并行扇出（Fan-out）操作 1。利用 LangGraph 的并发执行模型，系统可以同时启动多个子智能体实例，并将大纲中的不同疑问分配给这些平行的工作线程 1。

在这一阶段，为了确保子智能体能够绝对专注地解决其所面临的具体问题，系统必须施加极强的物理隔离与提示词隔离 1。主管节点的提示词中被植入了严厉的约束指令，明确剥夺了其直接处理海量网页数据或亲自执行网络浏览操作的权限，从而彻底防止其工作记忆过载 1。主管唯一的任务就是分析当前的状态、选择合适的子智能体工具并分配任务。与此同时，并发生成的子智能体则接收到专门定制的专注型提示词，它们被要求彻底无视全局研究简报的广阔范围，仅针对被分配到的单一微小话题进行深度挖掘，并被严格限制在一个 API 调用预算内（例如针对简单的事实核查只允许 2-3 次工具调用，而对复杂的因果链分析则允许探索至预设的最大值）1。

在子智能体的内部逻辑中，系统实现了一个精妙的“搜索-阅读-反思”微循环 2。子智能体在调用搜索引擎工具获取网页内容并将其解析为可读文本后，不会盲目地将内容直接提交。它会利用自身的推理能力评估当前获取的信息深度是否足以完美回答其被分配的子疑问（即触发 is\_sufficient 状态判定）13。如果模型反思后认为证据链存在断层或发现了新的知识盲区，它将自动根据缺失的上下文重写查询语句，生成新的线索，并自主发起新一轮的网络检索 13。这种带有自我纠错机制的内部微循环，使得子智能体具备了人类研究员般“顺藤摸瓜”的高级情报挖掘能力。

### **第三阶段：多重博弈、同行评审与全局报告合成**

当所有的子智能体都耗尽了它们的探索预算，或者其内部的 is\_sufficient 标志被悉数触发后，它们所经历压缩提纯的高密度情报将被统一汇集到 Supervisor 管理的全局库中 13。此时，系统正式进入报告合成与生成阶段。

早期的开源实现中曾尝试让不同的子智能体分别撰写报告的独立章节，然后再进行拼接。然而，大量的工程实践证明，这种做法不可避免地会导致最终报告行文风格严重割裂、上下文逻辑不连贯以及前后矛盾 1。因此，本架构坚决选择集中化的一体生成策略。所有汇集而来的高纯度上下文将被打包交给一个专职的最终生成节点。该节点在原始研究简报的宏观指导下，运用其强大的长文本统筹能力，通过“一次性”（One-Shot）生成机制完成整份连贯报告的输出 1。

但这并非结束。为了达到甚至超越人类专家的学术级或商业级输出质量，系统在此合成环节引入了受前沿学术论文（如 STORM）启发的多智能体多轮博弈机制 2。在这一高级模式下，系统动态引入一个 ChiefEditorAgent（主编智能体）来统筹全局。主编智能体不会亲自下场修改，而是将初步生成的一万字草稿交给一个极度挑剔的专门化 ReviewerAgent（审查智能体）进行苛刻的质量评估 2。审查智能体的提示词被设定为以批判性的眼光寻找瑕疵，它会逐段扫描报告，针对任何与大纲偏离的论述、缺乏强有力数据支撑的论点、逻辑推演的漏洞以及文风的不一致提出具体且尖锐的修改意见 2。随后，一份包含了所有批评意见的反馈报告与原始草稿被传递给 ReviserAgent（修订智能体）。修订智能体接收反馈后，针对性地对报告的缺陷部位进行重写和精准修改 2。这种“生成-审查-修订”的闭环将在系统设定的最高迭代次数内持续进行，直到审查智能体无法找出新的明显瑕疵，确保报告质量跃升至预设的严苛阈值之上 2。

## **第四章：针对 Claude 3.5 Sonnet 的高阶提示词工程范式**

在决定不进行底层模型微调（Fine-tuning）的约束前提下，系统最终展现出的“智商”上限和行为可靠性，极大程度上取决于向模型输入的提示词（Prompt）工程的质量。Claude 3.5 Sonnet 模型具有其极为独特且不断演进的指令遵循逻辑与行为偏好，深刻掌握并利用这些特性，是成功架构 Deep Researcher 项目不可或缺的核心能力 17。

### **从“推测意图”到“字面执行”的认知范式转变**

以往世代的大语言模型往往被设计为极度“讨好”用户，它们倾向于推测用户简短指令背后的模糊意图，并主动补充大量未经请求的附加内容。然而，自 Claude 3.5 世代发布以来，Anthropic 从根本上重构了模型遵循指令的底层逻辑，将其塑造为一个字面意义上的绝对指令执行器（Literal-minded executor）18。

在当前的架构实践中，如果开发者在提示词中没有极其明确、细致地要求系统输出特定的格式、采用某种深度的分析方法或包含特定的图表，Claude 模型将绝对不会主动提供任何被视为“超纲”的内容 18。因此，开发者必须彻底停止将模型视为无所不知且善解人意的魔法棒，而是应当将其视为一位极其聪明、逻辑严密但对你所在组织的特定业务规范一无所知的新进员工 17。在撰写驱动整个深度研究系统的宏观提示词时，必须使用详尽的、确定性的规则定义，抛弃所有诸如“请提供一份尽可能详尽的报告”或“请深入分析”之类含糊不清的形容词。必须用极其具体的量化指标或强制的结构化要求取而代之，例如明确规定“你的输出必须包含四个段落，每个段落必须提供至少三个跨来源的数据对比，且严禁使用 Markdown 列表格式而必须采用连贯的叙述性散文” 17。

### **深度嵌合的 XML 标签化与结构化通信协议**

Claude 模型在对其进行强化学习与预训练的漫长阶段，被深度灌输了对 XML 标签解析的高度敏感性与顺从性。这一特性使得 Claude 成为构建复杂多智能体系统时实现精确指令路由和结构化通信的绝佳载体 19。在架构动辄数千 Token 的多级提示词时，绝不能依赖单纯的自然语言换行或简单的符号分割。系统必须全面拥抱描述性的 XML 标签体系，将主控指令、历史上下文、参考数据集、提供给模型的 Few-shot 示例以及最终要求的输出格式进行严格的物理隔离与空间划分 17。

在实际的工程部署中，一个用于驱动核心 Supervisor 节点的系统提示词模板应当遵循如下高度结构化的层级设计 20：

XML

\<system\_role\>  
你是一个顶级的深度研究系统的主管智能体。你的核心任务是协调多个专业子智能体，依据研究简报完成庞大复杂的信息综合任务。  
\</system\_role\>

\<operating\_rules\>  
1\. 绝对禁止你自己直接回答用户的问题或直接捏造研究内容。  
2\. 你必须且只能通过调用预设的工具系统来委派任务给子智能体。  
3\. 每次决定分配新任务时，你必须生成一个目标明确的 \<task\_definition\> 载荷。  
\</operating\_rules\>

\<global\_context\>  
{$RESEARCH\_BRIEF}  
\</global\_context\>

\<working\_memory\>  
{$CURRENT\_STATE\_JSON\_DUMP}  
\</working\_memory\>

\<instructions\>  
仔细审查上述 \<working\_memory\> 中积累的数据与 \<global\_context\> 的目标偏差。  
请决定下一步的最高优先级行动。  
在决定调用任何工具或声明任务完成之前，你绝对必须首先在 \<thinking\> 标签内详细记录你的逻辑推演过程、分析数据矛盾并权衡不同工具的适用性。  
\</instructions\>

通过部署这种层级分明、嵌套严密的 XML 结构，Claude 3.5 Sonnet 能够利用其强大的注意力机制，精确无误地解析混杂在超长上下文中的海量关键变量 17。这从根本上避免了模型在处理大量无关噪声时，将核心指令与背景参考数据混为一谈而引发的灾难性幻觉错误。

### **显式逻辑沙盒：扩展思维 (Extended Thinking) 与强制思维链**

在面对需要跨越多个逻辑跳跃的复杂决策节点时，强制模型显式地实施思维链（Chain of Thought, CoT）推理，是当前压制幻觉率、提升决策胜率的最核心且最有效的手段 22。在为 Claude 3.5 设计提示词架构时，必须系统性地引入强制的显式思考空间，明确要求模型在给出任何行动指令或最终输出之前，必须首先在一个预先设定的标签（如 \<thinking\> 或 \<scratchpad\>）内部进行不受拘束的沙盒式逻辑推演 2。

这种被统称为交错式思考（Interleaved Thinking）的高阶机制，深刻改变了模型处理数据的方式。它允许模型在接收到外部检索工具返回的海量、杂乱甚至是自相矛盾的数据后，不会急于给出一个敷衍的结论。相反，模型会在 \<thinking\> 标签内首先仔细评估这些外部数据的可靠性和相关性，敏锐地识别出不同来源之间存在的潜在矛盾，进而深思熟虑地决定是继续深挖、调整搜索策略还是可以得出阶段性结论 2。

在具体的工程管道实现中，系统后台服务应当捕获并完整记录模型输出在 \<thinking\> 标签内的所有思维过程，将其持久化至日志系统中以供未来的调试、性能审计和提示词逆向优化。然而，在前端向终端用户呈现研究进度或最终报告结果时，系统在解析输出时会完全剥离并隐藏这些带有思考痕迹的标签内容。这种精妙的架构设计，在丝毫没有损害终端用户阅读体验和界面简洁性的前提下，利用了额外消耗的计算 Token，在后台换取了模型决策质量呈数量级的大幅跃升 21。此外，为了确保模型绝对服从这一规则，开发者应当通过 API 的消息数组结构，在 Assistant 角色的最新回复中强行注入一个以 \<thinking\> 开头的字符串前缀（Prefill 预填充技巧）。这种做法能够形成强有力的强制引导，打破模型可能由于惯性而直接跳跃到给出肤浅结论的倾向，迫使其立即进入深度的逻辑推演状态 19。

## **第五章：外部感知与数据摄取基础设施 (Data Ingestion)**

无论云端的 Claude 模型拥有多么深邃的推理能力与庞大的参数规模，深度研究智能体展现出的最终智商上限，从根本上受制于其感知外部广阔信息环境的“视觉”质量，即底层数据网络摄取与解析工具链的效能。在真实的互联网环境中，未经处理的原始 HTML 文档通常犹如一座信息垃圾场，充斥着庞大的 JavaScript 交互脚本、冗长的导航栏菜单、无意义的 CSS 样式代码以及成堆的广告标签。这些巨量的数字噪声如果被毫无节制地输入系统，不仅会以惊人的速度榨干模型宝贵的上下文 Token 预算（导致高昂的 API 调用成本），更会严重污染并干扰模型脆弱的注意力机制（Attention Mechanism），导致提取出的信息支离破碎甚至发生严重的逻辑扭曲 1。因此，为智能体配备专门针对大语言模型阅读习惯优化的高保真摄取基础设施，是构建成功系统的基石。

### **LLM 原生检索引擎生态的深度对比与战略选型**

当前开源社区和商业市场涌现出多款标榜“LLM 友好”的网络交互工具。系统架构师在搭建坚固的数据管道时，必须根据不同研究阶段的特殊需求，在信息获取的实时性、上下文保真度以及 Token 消耗带来的计算负担之间进行精准权衡。以下对当前生产级主流摄取基础设施进行全方位剖析：

| 数据摄取基础设施框架 | 核心机制与底层技术架构特性 | 最佳适用业务场景与系统架构权衡 |
| :---- | :---- | :---- |
| **Firecrawl** | 一个极具侵略性的数据管道 API，将元搜索引擎发现能力与深度全站穿透爬虫紧密集成。它在后台维护预热的浏览器集群以实现完美的 JavaScript 动态渲染，能够穿透复杂的反爬防御，将极其臃肿的现代动态网页直接转化提炼为极度纯净、无损的 Markdown 格式文档或高度结构化的 JSON 数据对象 1。 | 是构建私有企业知识 RAG 管道以及处理需要获取绝对完整网页上下文以进行深度全盘逻辑合成的重型研究任务的终极选择。尽管其具备无与伦比的页面穿透力和灵活多变的格式输出能力，但其系统返回的 Payload 数据包体积往往异常庞大。这直接导致系统的底层状态机必须具备极度强悍的递归摘要、状态压缩和 Token 动态截断能力，否则极易引发系统的内存溢出或突破模型的上下文极值 1。 |
| **Tavily** | 在业界明确被定位为“搜索优先”（Search-first）并专为 AI 智能体设计的敏捷 API 端点。它通过执行极速的实时网络搜索，并在其服务器底层预先利用紧凑型机器学习模型对搜索结果进行严苛的相关性评分排序和预先摘要。最终，它不返回原始网页，而是直接向智能体抛出包含精准来源引用的浓缩事实结果片段 1。 | 极其契合系统在需要以极低的延迟快速跨越大量独立信息源进行横向事实核查与跨域知识合成的场景。它的应用大幅削减了向大模型输入原始网页文本的绝对数量，极大地降低了系统对智能体超长上下文窗口的强依赖，显著减轻了整个多智能体网络的计算压舱物负担和运行延迟 1。 |
| **Crawl4AI** | 一款深受欢迎的开源、支持完全本地私有化部署的高性能网页爬虫框架。它最大的技术亮点在于内置了多种专为 LLM 注意力机制优化的智能文本分块（Chunking）策略与自适应信息过滤算法（如 BM25 算法过滤器），能够出色且稳健地处理重度依赖异步 JavaScript 渲染的复杂现代前端应用架构 1。 | 对于那些极其重视数据主权、旨在构建内部高度机密情报分析流水线、同时在运行成本预算上受到严格限制且具备自有基础设施维护能力的资深工程团队而言，这是目前市面上性价比最高的解决方案。其最令人瞩目的自适应爬取智能机制，能够基于一套复杂的多层评分系统，自主决定在何时停止跟随页面内的嵌套链接，从而完美防止了资源的无谓消耗和对不相关网页的过度爬取 1。 |

在设计一套健壮的 Deep Researcher 系统架构时，单一工具的局限性显而易见。因此，本报告强烈推荐采用**自适应混合感知战略**。在研究生命周期的初期——即探索性、广度优先的发散搜索阶段（主要目的是寻找破题方向、验证事实存在性与构建初步知识图谱）——系统应优先调用 Tavily 等工具库，以实现高并发、低延迟的快速认知反馈；而当系统经过几轮迭代，成功锁定特定存在极高价值的深水区目标（例如长篇深度的技术剖析报告、涉及复杂论证的顶级学术论文长文或包含海量数字的特定企业跨年财报）时，控制流应当果断切换至 Firecrawl 或 Crawl4AI 引擎，发起全面深入的全文解析与精准的 Markdown 格式提取操作，从而确保高价值情报的一分一毫都不会流失 1。这种结合广度扫描与深度钻探的混合策略，构成了系统强大感知能力的核心竞争力。

## **第六章：报告合成与精准补丁式文件编辑机制 (Patch-based Editing)**

在长周期深度研究任务临近尾声的关键阶段，系统的最终输出绝不仅仅是几句闲聊般的总结。它往往需要生成长达数万字的专业洞察报告，或是在涉及成百上千个文件的复杂代码仓库中精准更新数十处底层配置。在这种严苛的应用场景下，如果系统的架构设计依然停留在传统思维，要求模型在每次修改哪怕一个标点符号时都必须重新输出整份长篇文档，将会引发灾难性的后果。这种做法不仅会不可避免地直接撞上模型 API 设定的最大绝对输出 Token 物理限制（例如强制截断在 8192 Token 处），更会导致系统产生令人难以忍受的时间延迟，并浪费巨额的不必要计算成本 29。

### **Token 高效的原子补丁生成协议**

为了从根本上彻底解决这一掣肘长文本处理的系统瓶颈，现代智能体架构必须在其核心工具链中引入基于补丁（Patch-based）的增量编辑与重构工具 2。在这个高级模式下，当智能体需要生成新章节或修改已存在的大型文稿时，它无需、也不被允许重写全文。相反，它只需利用模型强大的结构化输出能力，生成遵循特定格式规范的微小原子补丁（Atomic Diffs）。随后，由部署在宿主环境中的本地系统层截获这些补丁，并将其精准应用到目标文件中 31。

在目前的开源最佳实践中，一个被大模型（尤其是经历了大量代码库训练的模型）广泛理解和精准生成的标准补丁协议结构通常如下所示 32：

\*\*\* Begin Patch \*\*\*

Update File: reports/global\_market\_analysis\_2026.md

@@

## **第三章：竞争格局与寡头垄断**

* 目前市场上主要由三家传统的硬件制造公司主导。  
* 目前市场上主要由三家传统的硬件制造公司主导，且它们均在 2026 年初秘密发布了新一代自研计算架构。  
  这清晰地表明了底层算力市场竞争的加剧与白热化。  
  \*\*\* End Patch \*\*\*

这种极其严谨的格式强制模型提供五个关键信息维度：明确的操作类型指令（是 Add 增加、Update 更新还是 Delete 删除）、精确的目标文件相对路径、用于粗略定位的上下文定位行（紧随 @@ 符号之后），以及严格标注符号的被删除内容（前置 \-）和被添加的崭新内容（前置 \+）32。

### **基于多级模糊匹配 (Fuzzy Matching) 的稳健应用算法引擎**

然而，生成补丁仅仅是第一步。将模型在云端生成的这些相对脆弱的文本补丁，无缝且安全地应用到处于持续变动中的本地文件系统中，是整个长文本编辑环节中最容易崩溃、最为脆弱的一环。由于大语言模型的固有特性，它们往往无法精确记忆并追踪文件在多次修改后当前真实的绝对行号。更糟糕的是，模型生成的用于锚定的上下文参考文本，经常会在微小的字符细节上（例如空格的数量、制表符与空格的混用、甚至操作系统的换行符 CRLF 差异）与本地文件的真实状态存在难以察觉的微观差异 32。因此，底层的应用引擎决不能采用死板且脆弱的绝对行号硬编码逻辑。系统必须在文件交互的底层工具层，实现一套基于渐进式多级模糊匹配（Progressive Fuzzy Matching）的高级容错算法逻辑 32。

当应用引擎从智能体手中接过补丁字符串时，必须严格执行以下阶梯式的匹配与应用策略 32：

1. **极速精确匹配 (Exact Match)**：这是成本最低的首选方案。引擎首先在内存中加载的最新目标文件内容里，寻找与补丁上下文字符串在每一个字节上都完全一致的段落。  
2. **忽略行尾符匹配 (Ignore Line Endings Fallback)**：若第一步的精确匹配不幸失败，引擎将启动第一次退避，放宽检索条件。它会运用正则表达式在比对时临时剥离或统一所有的换行符（抹平 Windows 与 Unix 系统的差异）并进行重试。  
3. **忽略全局空白字符匹配 (Ignore Whitespace Fallback)**：若仍未命中目标，引擎将采取更为激进的正则匹配策略，在内存比对时忽略文本中所有的前导缩进、连续空格和制表符。因为这些视觉空白往往是模型最容易出现幻觉或记忆模糊的地方。  
4. **动态滑动窗口与高级编辑距离算法 (Sliding Window Levenshtein Distance)**：针对那些经历了严重修改、甚至上下文也发生了局部变异的极度复杂差异，引擎将祭出最终的杀手锏。它会建立一个动态调整大小的滑动窗口，在目标文件的文本流中缓慢扫描，逐一计算当前文本块与补丁上下文之间的 Levenshtein 编辑距离。系统会预先设定一个严苛但具有包容性的相似度容忍阈值（例如 90% 的字符串相似度），最终选取得分最高且成功超越该安全阈值的区域，作为补丁的真实应用目标地点 32。

如果在此引擎耗尽了所有的多级回退匹配策略后，依然无奈地发现无法安全地应用补丁，系统的防御底线要求它绝不能陷入静默崩溃或执行可能会破坏原文件的强行覆盖。相反，系统底层必须拦截这次失败的操作，并立即向发起调用的智能体返回一份结构化、信息丰富的错误诊断报告（通常是 JSON 格式，其中包含具体在寻找哪一行时遭遇了匹配失败以及周边相关的真实文件内容上下文）。这一机制将主动触发智能体的逻辑闭环，促使其根据新的真实环境反馈，自我修正认知错误并重新审慎地生成一份更为精确的补丁 32。

## **第七章：事实核查、信任锚点与引用代理系统 (CitationAgent) 的工程实现**

Deep Researcher 系统之所以能够在企业级应用和严肃学术研究中立足，并与普通的闲聊型 AI 机器人划清绝对的界限，其核心特征在于其输出的长篇研究报告必须具备不容置疑的事实严谨性（Factual Grounding）和完美的溯源能力。由于大语言模型的运作机制基于概率生成，这使得它们在合成海量信息时，始终伴随着潜在的幻觉风险。为了从系统架构的根源上彻底根除这一风险，系统架构师必须果断地解耦“内容报告生成”与“事实来源核查”这两项截然不同的系统职能，并在管道的末端部署具有绝对一票否决权的专用引用智能体（CitationAgent）37。

### **严苛引用的强制注入与核验机制**

在主工作流（无论是 Supervisor 主管节点还是协同的各子智能体）完成对所有信息的提炼，并起草出初步的综合报告草稿之后，所有的原始数据源文档（包括从网上抓取的长文、内部数据库提取的 PDF 等）以及这份尚未标注任何引用的草稿，将被系统一并打包，传递给处于独立沙盒中的 CitationAgent 38。

该智能体运行在一个被严格物理与逻辑隔离的纯净上下文中。其系统提示词被设计为施加了极度严厉且毫不妥协的事实约束边界：它被明确告知，绝对禁止利用自身的先验知识创造任何一丝一毫的新观点或修改报告的论点结构。它的唯一使命，只能是极其枯燥地基于传入的源文件阵列，对草稿中所陈述的每一项微小的客观事实声明，进行地毯式的回溯寻根。

当 CitationAgent 在浩如烟海的原始文档中成功匹配到支撑某一句话的事实来源时，它必须在这句话的句末，强制插入符合严格格式规范的精确内联引用标记。系统在底层架构层面必须强制确立引用的标准化输出序列协议，以确保后续机器解析的可靠性。例如，强制使用特定的结构化元数据括号标记：\[file\_id:3-page\_num:22\] 或者是针对网页内容的 \[source\_id:abc\] 41。任何未能找到对应坚实文献支撑的草稿声明，都必须被标记为存疑，甚至在最终的修订循环中被系统无情剔除。

### **针对复杂文档环境的精准高亮与 DOM 锚定技术**

如果仅仅是在生成的报告文本末尾附上一串晦涩的文档 ID，虽然在逻辑上完成了溯源，但这远未达到现代化交互界面的卓越标准。为了在最终面向终端用户的应用界面（UI）中提供极具冲击力和信任感的溯源体验（即当用户用鼠标点击任何一个引用上标时，系统能够瞬间跳转并直接在原始的 PDF 文档页面或网页缓存中，用高亮颜色精确圈出支撑该论点的原始句子），系统底层必须解决极其复杂的跨媒介坐标映射难题 41。

在实际的工程运行中，由于 RAG 管道在提取文本时所采用的各种预处理手段、PDF 文档进行 OCR 识别时产生的不可避免的噪点，以及大语言模型在生成引用上下文时为了通顺而擅自进行的细微改写（例如改变了标点符号的种类、或者自作主张地使用了省略号来截断长句），使得模型返回的引用文本字符串与真实文档中用于渲染的文本层之间，经常存在细微的字符错位。面对这种混乱的现实，纯粹依赖绝对相等的字符串匹配机制将会面临惨败。因此，系统底层需要突破常规，实现一套基于复杂近似字符串匹配理论的高级解析机制 41。

当后端应用引擎接收到由 CitationAgent 返回的密布着内联引用标记的定稿报告时，解析器将被激活并严格执行以下重负荷计算操作：

1. **标识符精准萃取**：首先利用极其强壮的正则表达式，从庞大的文本流中一次性提取出所有隐藏在括号内的引用标识符以及模型附带提供的参考上下文短语 41。  
2. **复杂断点与省略号重构**：大模型极度偏爱使用省略号来代表较长的引文。如果解析器检测到模型截断了引文（例如输出了类似 前文核心论点...后文总结陈词 的格式），解析器在内存中将该目标字符串暴力拆分为独立的前缀子串和后缀子串，随后将它们分配给独立的线程在庞大的源文档语料库中分别进行坐标定位，再在空间逻辑上进行拼合 41。  
3. **近似匹配与滑动窗口扫描**：对于那些存在细微错字的文本，解析器利用高度优化的编辑距离（Levenshtein Distance）统计算法，设定一个经过海量实验测试得出的合理 MAX\_DISTANCE 容忍阈值（例如允许在特定长度的句子中存在至多 8 个字符的编辑变异，以完美包容 OCR 识别带来的拼写误差）。随后，在被引用的庞大源文档的文本层中进行密集的滑动窗口计算匹配 41。  
4. **像素级 DOM 与 PDF 坐标映射**：在寻找到得分最高的最优匹配区域后，底层引擎计算出该匹配段落在全局文档字符串中的精确字符偏移量（Offsets）。随后，通过复杂的桥接算法，将这些线性偏移量映射转化为前端网页特定的 DOM 节点边界（Node Boundaries）坐标，或 PDF 渲染引擎专用的 X-Y 绝对空间坐标。正是这最终的一跃，才实现了令人震撼的像素级引用高亮渲染效果 41。

## **第八章：系统容错防御、弹性架构与生产级部署之道**

当深度研究智能体被部署到不可控的真实互联网环境中，开启其可能长达数小时的自主探索航程时，其面临的运行环境是极度险恶的。外部商业 API 的无预警限流与宕机、模型在极度复杂的指令下偶然发生的输出格式违规、甚至是底层网络请求的随机超时，这些异常并非可能发生，而是必然发生的常态。在一个高度耦合的由无数超级步驱动的多智能体网络中，任何一个微小节点的未经捕获的异常，都可能引发多米诺骨牌效应，导致整个计算网络崩溃，让投入了巨额 API 成本和大量时间的深度研究工作瞬间毁于一旦。因此，必须在这套精密的逻辑机器外围，浇筑工业级的可靠性防御装甲与弹性容错架构 42。

### **绝对的幂等重试与指数退避算法 (Exponential Backoff)**

当子智能体在执行过程中尝试调用外部网络深层抓取工具，或者向第三方大模型 API 提供商发起巨量推理请求时，如果遭遇了临时性的网络抖动故障或触发了严格的速率限制（Rate Limit），系统的顶层架构绝对不能简单粗暴地抛出运行时异常并终止整个主进程。

作为替代，必须在底层网络请求和工具执行接口的核心地带，强制封装经过千锤百炼的自动重试框架逻辑。这种重试并非盲目的高频轮询，而是必须采用科学的指数退避（Exponential Backoff）算法。当发生初次失败时，系统可能仅仅延迟 1 秒即发起重试；若依然失败，则延迟翻倍至 2 秒、继而 4 秒、8 秒，依此类推。这种随着失败次数增加而呈指数级放缓的重试节拍，是防止在外部系统或己方网络本来就已经处于极度高负载和濒临崩溃状态时，因密集的重试请求而引发灾难性雪崩效应的关键所在 42。

更为深刻的是，系统架构师必须在设计之初就确保所有允许被重试的工具与内部接口的实现都绝对满足幂等性（Idempotency）。幂等性保证了即使在极其恶劣的网络波动中，由于各种原因导致某一个工具调用被底层引擎重复执行了多次，其对系统全局状态或外部存储结构（例如向量数据库的文档索引库）所造成的最终副作用，也绝对等同于仅仅成功执行了一次的结果。只有实现了绝对的幂等，重试机制才能成为保护系统免受网络风暴摧残的坚固盾牌，而不是引发数据重复与状态混乱的元凶 43。

### **智能断路器 (Circuit Breakers) 与柔性优雅降级策略**

在由成百上千次微观决策构成的多智能体迷宫中，不可避免地会出现某个不幸的子智能体在解析一个包含新型反爬虫机制的复杂页面时，陷入了可怕的逻辑死循环，它可能会在这个无用的页面上不断发起无意义的解析重试。为了防止这种灾难性的局部级联故障在数分钟内耗尽项目所有的 API 预算并锁死全局线程池，系统在顶层架构中必须强制引入微服务架构中久经考验的智能断路器（Circuit Breaker）机制 43。

部署在系统核心部位的守护监控模块会毫不疲倦地实时追踪并记录系统中每一个活动子智能体及其调用的每一个工具的连续失败次数。一旦它发现某个实体的连续失败次数触碰了预先设定的安全红线（例如在 2 分钟内连续 3 次关键工具调用失败），智能断路器将被立刻无情触发。系统将强制切断该特定子节点的一切外部资源访问权限，截断其执行轨迹 44。

在断路器被触发的悲观时刻，系统不应宣告整个研究任务的失败，而是应当立即启动柔性优雅降级（Graceful Degradation）策略。断路器会将该被掐断的任务分支标记为“执行失败”或“仅部分收集完成”，随后发送特定的控制信号通知处于神经中枢位置的 Supervisor 主管节点。主管节点在接收到信号后，会理智地放弃这一存在致命缺陷的研究支线，依靠其他健康子智能体已经收集到的海量跨来源数据网络，继续坚定地推进并完成最终核心报告的生成逻辑。这种丢车保帅的降级策略，确保了系统的最核心商业价值（即按时交付一份具备极高参考价值的深度研究报告）永远不会因为浩瀚互联网中某个微小边缘数据源的失效而遭到毁灭性的彻底停摆 43。

## **结语**

从零开始构建一个具备工业级稳定性的 Deep Researcher 系统，是一项融合了最前沿的人工智能推理理论与极其严苛的分布式系统工程实践的浩大工程。它绝非简单地堆砌提示词或频繁调用 Claude 3.5 Sonnet 的模型 API。它的本质，是在大语言模型极其惊艳却又充满非确定性与发散性的逻辑推理海洋之上，人工套上一层由强类型约束、精准状态追踪与严密错误处理编织而成的高度确定性的工程控制论体系。

通过引入以 LangGraph 为核心的多智能体图状拓扑架构，我们从根本上拆解并解决了单体模型面临的上下文物理边界崩溃问题；依靠极其严苛的数据校验字典和外挂式的 Todo Files 机制，我们赋予了系统在漫长计算周期中保持逻辑清醒与从灾难中瞬间无损恢复的惊人能力；通过施加针对 Claude 3.5 世代特性的深度 XML 标签化结构提示词与强制开辟的显式沙盒交错思维链，我们极大地压榨并释放了模型进行高阶复杂推理的极限物理潜力；最后，借助能够实现像素级高亮的复杂近似字符串追踪引用系统、精密的补丁式渐进文档编辑算法以及坚如磐石的包含重试与断路器在内的弹性防御设施，我们为这套精密的智慧大脑筑起了一道抵御混沌互联网环境的钢铁长城。

这套全面详尽的架构方案不仅标志着人工智能应用已经完全从单纯的被动式对话响应玩具，成功进化并跃升为能够自主规划、长程执行、自我纠错并创造真实商业价值的自动化生产力矩阵，更绘制了未来十年知识密集型工作全面自动化与智能化的核心基础设施蓝图。严格遵循本指南所确立的宏伟架构范式、核心算法逻辑与底层工程防御策略，任何具备决心的开发团队都可以构建出稳定、极速且具备惊人自主驱动深度挖掘能力的超级智能体集群。

#### **引用的著作**

1. Deep Research 技术探索与实现, [https://drive.google.com/open?id=18jCm\_-F\_7kavrerUf7nxuB47u32YTbpYjRKLTRBDc78](https://drive.google.com/open?id=18jCm_-F_7kavrerUf7nxuB47u32YTbpYjRKLTRBDc78)  
2. Deep Research  
3. Subagents \- Docs by LangChain, 访问时间为 三月 9, 2026， [https://docs.langchain.com/oss/python/langchain/multi-agent/subagents](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents)  
4. Multi-agent \- Docs by LangChain, 访问时间为 三月 9, 2026， [https://docs.langchain.com/oss/python/langchain/multi-agent](https://docs.langchain.com/oss/python/langchain/multi-agent)  
5. Understanding the LangGraph Multi-Agent Supervisor | by akanshak \- Medium, 访问时间为 三月 9, 2026， [https://medium.com/@akanshak/understanding-the-langgraph-multi-agent-supervisor-00fa1be4341b](https://medium.com/@akanshak/understanding-the-langgraph-multi-agent-supervisor-00fa1be4341b)  
6. Building Parallel Workflows with LangGraph: A Practical Guide | by Manu Francis | GoPenAI, 访问时间为 三月 9, 2026， [https://blog.gopenai.com/building-parallel-workflows-with-langgraph-a-practical-guide-3fe38add9c60](https://blog.gopenai.com/building-parallel-workflows-with-langgraph-a-practical-guide-3fe38add9c60)  
7. BrijeshRakhasiya/Deep-Research-Agent-From-Scratch: Multi-agent AI research system with LangGraph, FastAPI & RAG. Parallel research orchestration inspired by OpenAI Deep Research. \- GitHub, 访问时间为 三月 9, 2026， [https://github.com/BrijeshRakhasiya/Deep-Research-Agent-From-Scratch](https://github.com/BrijeshRakhasiya/Deep-Research-Agent-From-Scratch)  
8. Build a LangGraph Multi-Agent system in 20 Minutes with LaunchDarkly AI Configs, 访问时间为 三月 9, 2026， [https://launchdarkly.com/docs/tutorials/agents-langgraph](https://launchdarkly.com/docs/tutorials/agents-langgraph)  
9. Graph API overview \- Docs by LangChain, 访问时间为 三月 9, 2026， [https://docs.langchain.com/oss/python/langgraph/graph-api](https://docs.langchain.com/oss/python/langgraph/graph-api)  
10. Workflows and agents \- Docs by LangChain, 访问时间为 三月 9, 2026， [https://docs.langchain.com/oss/python/langgraph/workflows-agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)  
11. Part 1: How LangGraph Manages State for Multi-Agent Workflows (Best Practices) \- Medium, 访问时间为 三月 9, 2026， [https://medium.com/@bharatraj1918/langgraph-state-management-part-1-how-langgraph-manages-state-for-multi-agent-workflows-da64d352c43b](https://medium.com/@bharatraj1918/langgraph-state-management-part-1-how-langgraph-manages-state-for-multi-agent-workflows-da64d352c43b)  
12. Building Intelligent Multi-Agent Systems with Pydantic AI | by Data Do GmbH \- Medium, 访问时间为 三月 9, 2026， [https://medium.com/@DataDo/building-intelligent-multi-agent-systems-with-pydantic-ai-f5c3d9526366](https://medium.com/@DataDo/building-intelligent-multi-agent-systems-with-pydantic-ai-f5c3d9526366)  
13. LangGraph 101: Let's Build A Deep Research Agent | Towards Data Science, 访问时间为 三月 9, 2026， [https://towardsdatascience.com/langgraph-101-lets-build-a-deep-research-agent/](https://towardsdatascience.com/langgraph-101-lets-build-a-deep-research-agent/)  
14. Building Long-Running Deep Research Agents: Architecture, Attention Mechanisms, and Real-World Applications | by Madhur Prashant | Medium, 访问时间为 三月 9, 2026， [https://medium.com/@madhur.prashant7/building-long-running-deep-research-agents-architecture-attention-mechanisms-and-real-world-11f559614a9c](https://medium.com/@madhur.prashant7/building-long-running-deep-research-agents-architecture-attention-mechanisms-and-real-world-11f559614a9c)  
15. file-todos | Skills Marketplace \- LobeHub, 访问时间为 三月 9, 2026， [https://lobehub.com/ru/skills/microck-ordinary-claude-skills-file-todos](https://lobehub.com/ru/skills/microck-ordinary-claude-skills-file-todos)  
16. What I Learned Building a Knowledge Graph for AI Agents \- DEV Community, 访问时间为 三月 9, 2026， [https://dev.to/trentbrew/what-i-learned-building-a-knowledge-graph-for-ai-agents-3e65](https://dev.to/trentbrew/what-i-learned-building-a-knowledge-graph-for-ai-agents-3e65)  
17. Prompting best practices \- Claude API Docs, 访问时间为 三月 9, 2026， [https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)  
18. We Tested 25 Popular Claude Prompt Techniques: These 5 Actually Work \- DreamHost Blog, 访问时间为 三月 9, 2026， [https://www.dreamhost.com/blog/claude-prompt-engineering/](https://www.dreamhost.com/blog/claude-prompt-engineering/)  
19. Prompt engineering techniques and best practices: Learn by doing with Anthropic's Claude 3 on Amazon Bedrock | Artificial Intelligence, 访问时间为 三月 9, 2026， [https://aws.amazon.com/blogs/machine-learning/prompt-engineering-techniques-and-best-practices-learn-by-doing-with-anthropics-claude-3-on-amazon-bedrock/](https://aws.amazon.com/blogs/machine-learning/prompt-engineering-techniques-and-best-practices-learn-by-doing-with-anthropics-claude-3-on-amazon-bedrock/)  
20. Advanced prompt templates \- Amazon Bedrock, 访问时间为 三月 9, 2026， [https://docs.aws.amazon.com/bedrock/latest/userguide/advanced-prompts-templates.html](https://docs.aws.amazon.com/bedrock/latest/userguide/advanced-prompts-templates.html)  
21. langgptai/awesome-claude-prompts \- GitHub, 访问时间为 三月 9, 2026， [https://github.com/langgptai/awesome-claude-prompts](https://github.com/langgptai/awesome-claude-prompts)  
22. Console prompting tools \- Claude API Docs, 访问时间为 三月 9, 2026， [https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-tools](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-tools)  
23. Firecrawl vs Tavily: Complete Comparison for AI Agents & RAG (2026), 访问时间为 三月 9, 2026， [https://www.firecrawl.dev/compare/firecrawl-vs-tavily](https://www.firecrawl.dev/compare/firecrawl-vs-tavily)  
24. 5 Tavily Alternatives for Better Pricing, Performance, and Extraction Depth \- Firecrawl, 访问时间为 三月 9, 2026， [https://www.firecrawl.dev/blog/tavily-alternatives](https://www.firecrawl.dev/blog/tavily-alternatives)  
25. Comparing 10 AI-Native Search APIs and Crawlers for LLM Agents \- Medium, 访问时间为 三月 9, 2026， [https://medium.com/towardsdev/comparing-10-ai-native-search-apis-and-crawlers-for-llm-agents-ed4130d22c67](https://medium.com/towardsdev/comparing-10-ai-native-search-apis-and-crawlers-for-llm-agents-ed4130d22c67)  
26. Crawl4AI vs. Firecrawl: The Free Markdown Pipeline \- YouTube, 访问时间为 三月 9, 2026， [https://www.youtube.com/watch?v=2G61uw07Dkg](https://www.youtube.com/watch?v=2G61uw07Dkg)  
27. What is the best scraper tool right now? Firecrawl is great, but I want to explore more options, 访问时间为 三月 9, 2026， [https://www.reddit.com/r/LocalLLaMA/comments/1jw4yqv/what\_is\_the\_best\_scraper\_tool\_right\_now\_firecrawl/](https://www.reddit.com/r/LocalLLaMA/comments/1jw4yqv/what_is_the_best_scraper_tool_right_now_firecrawl/)  
28. Best Open-Source Web Crawlers in 2026 \- Firecrawl, 访问时间为 三月 9, 2026， [https://www.firecrawl.dev/blog/best-open-source-web-crawler](https://www.firecrawl.dev/blog/best-open-source-web-crawler)  
29. Step-DeepResearch Technical Report \- arXiv, 访问时间为 三月 9, 2026， [https://arxiv.org/html/2512.20491v1](https://arxiv.org/html/2512.20491v1)  
30. Turning the Tide: Repository-based Code Reflection \- ACL Anthology, 访问时间为 三月 9, 2026， [https://aclanthology.org/2025.findings-emnlp.377.pdf](https://aclanthology.org/2025.findings-emnlp.377.pdf)  
31. Like a tide, your codebase evolves \- and CodeTide helps you move with it, intelligently. \- GitHub, 访问时间为 三月 9, 2026， [https://github.com/BrunoV21/CodeTide](https://github.com/BrunoV21/CodeTide)  
32. Code Surgery: How AI Assistants Make Precise Edits to Your Files ..., 访问时间为 三月 9, 2026， [https://fabianhertwig.com/blog/coding-assistants-file-edits/](https://fabianhertwig.com/blog/coding-assistants-file-edits/)  
33. Fuzzy file search powered by LLM | by Dinh Long Huynh \- Medium, 访问时间为 三月 9, 2026， [https://medium.com/@dinhlong240600/fuzzy-file-search-powered-by-llm-d4977c01c2a1](https://medium.com/@dinhlong240600/fuzzy-file-search-powered-by-llm-d4977c01c2a1)  
34. How CLI-Based Coding Agents Work? by cbarkinozer | Softtech \- Medium, 访问时间为 三月 9, 2026， [https://medium.com/softtechas/how-cli-based-coding-agents-work-33a36cf463fa](https://medium.com/softtechas/how-cli-based-coding-agents-work-33a36cf463fa)  
35. FuzzyTM: A Python package for Fuzzy Topic Models \- Towards Data Science, 访问时间为 三月 9, 2026， [https://towardsdatascience.com/fuzzytm-a-python-package-for-fuzzy-topic-models-fd3c3f0ae060/](https://towardsdatascience.com/fuzzytm-a-python-package-for-fuzzy-topic-models-fd3c3f0ae060/)  
36. LLM Patch Driver \- GitHub, 访问时间为 三月 9, 2026， [https://github.com/NickSherrow/llm\_patch\_driver](https://github.com/NickSherrow/llm_patch_driver)  
37. Anthropic: Building a Multi-Agent Research System for Complex Information Tasks \- ZenML, 访问时间为 三月 9, 2026， [https://www.zenml.io/llmops-database/building-a-multi-agent-research-system-for-complex-information-tasks](https://www.zenml.io/llmops-database/building-a-multi-agent-research-system-for-complex-information-tasks)  
38. How we built our multi-agent research system — Anthropic | by Kushal Banda, 访问时间为 三月 9, 2026， [https://ai.plainenglish.io/how-we-built-our-multi-agent-research-system-5f5e10b2a8d6](https://ai.plainenglish.io/how-we-built-our-multi-agent-research-system-5f5e10b2a8d6)  
39. FlowSearch: Advancing deep research with dynamic structured knowledge flow \- arXiv, 访问时间为 三月 9, 2026， [https://arxiv.org/html/2510.08521v1](https://arxiv.org/html/2510.08521v1)  
40. How we built our multi-agent research system \\ Anthropic, 访问时间为 三月 9, 2026， [https://www.anthropic.com/engineering/multi-agent-research-system](https://www.anthropic.com/engineering/multi-agent-research-system)  
41. Creating Rich Citation Experiences with LLMs \- Shift | AI, 访问时间为 三月 9, 2026， [https://www.shifthq.ai/blog/creating-rich-citation-experiences-with-llms](https://www.shifthq.ai/blog/creating-rich-citation-experiences-with-llms)  
42. 5 Recovery Strategies for Multi-Agent LLM Failures \- Newline.co, 访问时间为 三月 9, 2026， [https://www.newline.co/@zaoyang/5-recovery-strategies-for-multi-agent-llm-failures--673fe4c4](https://www.newline.co/@zaoyang/5-recovery-strategies-for-multi-agent-llm-failures--673fe4c4)  
43. Multi-Agent System Reliability: Failure Patterns, Root Causes, and Production Validation Strategies \- Maxim AI, 访问时间为 三月 9, 2026， [https://www.getmaxim.ai/articles/multi-agent-system-reliability-failure-patterns-root-causes-and-production-validation-strategies/](https://www.getmaxim.ai/articles/multi-agent-system-reliability-failure-patterns-root-causes-and-production-validation-strategies/)  
44. Why Multi-Agent AI Systems Fail and How to Prevent Cascading Errors \- Galileo AI, 访问时间为 三月 9, 2026， [https://galileo.ai/blog/multi-agent-ai-failures-prevention](https://galileo.ai/blog/multi-agent-ai-failures-prevention)  
45. Building Resilient Multi-Agent Systems with Google ADK: A Practical Guide to Timeout, Retry, and Fallback Patterns | by sarojkumar rout \- Medium, 访问时间为 三月 9, 2026， [https://medium.com/@sarojkumar.rout/building-resilient-multi-agent-systems-with-google-adk-a-practical-guide-to-timeout-retry-and-1b98a594fa1a](https://medium.com/@sarojkumar.rout/building-resilient-multi-agent-systems-with-google-adk-a-practical-guide-to-timeout-retry-and-1b98a594fa1a)
