# DriveFlow Agent: 核心模块边界

本文档定义了 DriveFlow Agent 管线中三个核心决策模块的严格职责与边界。该架构保证了模块作用域之间的零重叠。

---

## 1. TaskGraphBuilder

**一句话职责 (Core Responsibility):**
负责将 Parser 输出的扁平化结构任务序列，转换为具备空间与时序依赖关系的有向无环图（DAG），不涉及任何后续的动态调度与执行策略。

**Input:**
- `tasks` (`List[Task]`): A flat list of parsed tasks.

**Output:**
- `task_graph` (`DirectedAcyclicGraph`): A topological structure representing task execution dependencies.

**不负责什么 (Out of Scope):**
- 不决定先执行哪个节点（这是 Planner 的事）。
- 不记录某个节点当前是否成功（这是 StateManager 的事）。
- 不处理外部 API 错误或用户意图不清的补充（仅做静态拓扑构建）。

---

## 2. TaskPlanner

**一句话职责 (Core Responsibility):**
负责根据当前的 TaskGraph 拓扑结构和全局 StateManager 状态，动态决策系统“下一步（Next Step）应当执行哪个具体 Node”，不涉及节点的具体执行与外部工具调用。

**Input:**
- `task_graph` (`DirectedAcyclicGraph`): The static dependency graph.
- `current_state` (`StateSnapshot`): The current context from the StateManager.

**Output:**
- `next_node_id` (`str`): The ID of the next task that is ready to be executed.

**不负责什么 (Out of Scope):**
- 不修改图的静态连接边（不能改变任务原本的拓扑设计）。
- 不调用任何实质性的地理位置或路线工具（这是 Executor/ToolRouter 的事）。
- 不持久化自身的决策历史（状态交由 StateManager 统一保存）。

---

## 3. StateManager

**一句话职责 (Core Responsibility):**
作为系统的唯一真实数据源（Single Source of Truth），负责集中管理和持久化全局执行上下文、节点状态流转以及历史决策记录，不涉及任何主动的业务逻辑推理。

**Input:**
- `state_update_event` (`Event`): Completed node results, retrieved tool data, or mid-task failures.

**Output:**
- `current_state_snapshot` (`StateSnapshot`): The unified context available for the Planner and Executor.

**不负责什么 (Out of Scope):**
- 不判断某条数据意味着“成功”还是“失败”（由 Executor 判别后传入明确事件）。
- 不主动触发下一个任务请求（完全被动地接受更新和读取请求）。
- 不解析用户输入或操作 TaskGraph 拓扑树。
