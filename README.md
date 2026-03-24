# DriveFlow Agent

## 1. Project Overview
DriveFlow Agent is an agent-oriented task planning system explicitly designed for conversational navigation in autonomous and smart-cabin environments. It effectively translates complex, multi-constrained natural language requests into structured execution graphs, orchestrating external map tools to fulfill user requirements end-to-end.

## 2. Problem Statement
Traditional navigation assistants handle simple, single-turn requests (e.g., "Navigate to X"). However, they fail at composite requests like "I want to go to Baiyun Mountain, but stop by a McDonald's on the way." DriveFlow Agent solves this by introducing a robust, decoupled agentic workflow that parses, graphs, plans, and executes multi-step dependencies seamlessly.

## 3. System Architecture
The system employs a rigid, acyclic pipeline enforcing absolute separation of concerns:
**User Input** → **Intent Parser** → **TaskGraphBuilder** → **TaskPlanner** → **Tool Router** → **Executor** ↔ **StateManager**

## 4. Core Modules
- **TaskGraphBuilder**: Converts parsed flat tasks into a Directed Acyclic Graph (DAG) denoting spatial and temporal dependencies. (No execution strategy involved).
- **TaskPlanner**: Dynamically resolves the "next optimal step" based on the static DAG and current global state. (No actual tool invocation).
- **StateManager**: Acts as the passive, Single Source of Truth (SSOT) tracking global context, node completion, and context flow. (No active business logic).

## 5. Example Flow
**Input:** *"I want to go to Baiyun Mountain, but stop by a McDonald's on the way."*
1. **Parser:** Extracts `restaurant (McDonalds)` and `destination (Baiyun Mountain)`.
2. **Graph Builder:** Generates DAG: `Search(McDonalds)` → `Navigate(McDonalds)` → `Navigate(Baiyun Mountain)`.
3. **Planner:** Identifies `Search(McDonalds)` as the unsatified root node.
4. **Executor/Tool:** Calls POI search, returns coordinates.
5. **StateManager:** Marks root node complete; triggers Planner loop for the next step.

## 6. Tech Stack
- **Language**: Python 3.11+
- **Framework**: FastAPI
- **Data Model**: Pydantic
- **LLM Integration**: OpenAI-compatible client (httpx)
- **Testing**: pytest

## 7. Demo Description
The project features a minimal local endpoint (`/parse`) validating pure intent extraction through mocked or real LLM backends. Development focuses entirely on backend pipeline rigor rather than UI or voice streaming overhead.

## 8. Project Value (for hiring)
- **Production-Ready Paradigm**: Demonstrates an understanding of bounded contexts, stateless services, and schema-driven development.
- **Agent Orchestration**: Moves beyond trivial wrapper scripts; implements a multi-stage cognitive architecture capable of self-correction and DAG traversal.
- **High Cohesion, Low Coupling**: Pydantic schemas enforce type safety across strictly isolated network, reasoning, and state boundaries.
