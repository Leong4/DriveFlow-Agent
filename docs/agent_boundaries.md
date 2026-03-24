# DriveFlow Agent: Core Module Boundaries

This document defines the strict responsibilities and boundaries of the three core decision-making modules in the DriveFlow Agent pipeline. The architecture guarantees zero overlap in scope.

---

## 1. TaskGraphBuilder

**Core Responsibility:**
Converts the parsed flat task sequence into a Directed Acyclic Graph (DAG) denoting spatial and temporal dependencies, without involving any dynamic scheduling or execution strategies.

**Input:**
- `tasks` (`List[Task]`): A flat list of parsed tasks.

**Output:**
- `task_graph` (`DirectedAcyclicGraph`): A topological structure representing task execution dependencies.

**Out of Scope (What it DOES NOT do):**
- Does not decide which node to execute first (This is the Planner's job).
- Does not record whether a node has succeeded or failed (This is the StateManager's job).
- Does not handle external API errors or clarify vague user intents (It only builds the static topology).

---

## 2. TaskPlanner

**Core Responsibility:**
Dynamically determines the "Next Step" (which specific node to execute next) based on the static DAG topology and the current global state from StateManager, without executing the node or invoking external tools.

**Input:**
- `task_graph` (`DirectedAcyclicGraph`): The static dependency graph.
- `current_state` (`StateSnapshot`): The current context from the StateManager.

**Output:**
- `next_node_id` (`str`): The ID of the next task that is ready to be executed.

**Out of Scope (What it DOES NOT do):**
- Does not modify the static edges of the graph (cannot change the original task topology).
- Does not invoke any actual geographical or routing tools (This is the Executor/ToolRouter's job).
- Does not persist its own decision history (State is completely delegated to the StateManager).

---

## 3. StateManager

**Core Responsibility:**
Acts as the Single Source of Truth (SSOT) centrally managing and persisting the global execution context, node state transitions, and historical decisions, without proactively engaging in business logic reasoning.

**Input:**
- `state_update_event` (`Event`): Completed node results, retrieved tool data, or mid-task failures.

**Output:**
- `current_state_snapshot` (`StateSnapshot`): The unified context available for the Planner and Executor.

**Out of Scope (What it DOES NOT do):**
- Does not judge whether a piece of data implies "success" or "failure" (The Executor determines this and passes an explicit event).
- Does not proactively trigger the next task request (It passively receives updates and serves read requests).
- Does not parse user input or manipulate the TaskGraph topology tree.
