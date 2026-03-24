# DriveFlow Agent

## 1. 项目简介 (Project Overview)
DriveFlow Agent 是一个面向智能座舱和自动驾驶场景的对话式导航任务规划 Agent 系统。它能够将带有复杂约束的自然语言请求转化为结构化执行图，并通过工具编排实现端到端的用户需求交付。

## 2. 核心痛点 (Problem Statement)
传统的车载语音助手往往只能处理“导航去X”这种单轮简单意图。当面对“我想去白云山，不过路上先找一家麦当劳”这类复合需求时，传统系统难以应对。DriveFlow Agent 引入了解耦的 Agentic 工作流，通过解析、构图、规划和执行等步骤，完美解决多步依赖的复杂导航问题。

## 3. 系统架构 (System Architecture)
系统采用严格的有向管线架构，强制实现控制反转和职责分离：
**用户输入** → **意图解析(Intent Parser)** → **构图(TaskGraphBuilder)** → **规划器(TaskPlanner)** → **工具路由(Tool Router)** → **执行器(Executor)** ↔ **状态机(StateManager)**

## 4. 核心模块边界 (Core Modules)
- **TaskGraphBuilder**: 负责将 Parser 输出的扁平化结构任务序列，转换为具备空间与时序依赖关系的有向无环图（DAG），不涉及任何后续的动态调度与执行策略。
- **TaskPlanner**: 负责根据当前的 TaskGraph 拓扑结构和全局 StateManager 状态，动态决策系统“下一步（Next Step）应当执行哪个具体 Node”，不涉及节点的具体执行与外部工具调用。
- **StateManager**: 作为系统的唯一真实数据源（SSOT），负责集中管理和持久化全局执行上下文、节点状态流转以及历史决策记录，不涉及任何主动的业务逻辑推理。

## 5. 示例流程 (Example Flow)
**输入:** *“我想去白云山，不过路上先找一家麦当劳。”*
1. **Parser:** 提取出 `restaurant (McDonalds)` 和 `destination (Baiyun山)` 两个独立任务。
2. **Graph Builder:** 构建有向图：`搜索(麦当劳)` → `导航至(麦当劳)` → `导航至(白云山)`。
3. **Planner:** 判断当前状态，吐出未满足的根节点 `搜索(麦当劳)`。
4. **Executor/Tool:** 挂载外部 POI 搜索接口，返回麦当劳坐标集。
5. **StateManager:** 记录节点完成状态，触发 Planner 进入下一个事件循环。

## 6. 技术栈 (Tech Stack)
- **语言**: Python 3.11+
- **框架**: FastAPI
- **数据层**: Pydantic
- **LLM 集成**: OpenAI 兼容协议客户端 (基于 httpx)
- **测试**: pytest

## 7. 演示说明 (Demo Description)
系统目前提供最小化本地接口（如 `/parse`），用于验证纯后端的意图抽取和模型边界测试。现阶段开发重心100%聚焦于底层编排管线的严谨性，舍弃 UI 动画或 ASR 语音推流等非核心链路的包袱。

## 8. 岗位匹配价值 (Project Value)
- **工程化素养**: 展现了对边界上下文 (Bounded Context)、无状态服务设计以及基于 Schema 校验的生产级代码理解。
- **复杂 Agent 编排**: 摆脱了“API 简单套壳大模型”的玩具项目范畴，实现了具备防幻觉、DAG 遍历以及自我纠错能力的多阶段认知架构。
- **高内聚低耦合**: 全链路依赖 Pydantic 强制类型安全，网络层、推理层和数据状态层严格物理隔离，高度吻合车企座舱后端的落地要求。
