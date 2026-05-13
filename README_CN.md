# DriveFlow Agent

DriveFlow Agent 是一个用于智能体课程项目的对话式导航 Agent demo。它模拟车载导航助手：用户用自然语言提出路线需求，系统解析成结构化任务，在目的地不确定或信息不足时先确认、候选选择或追问，再继续构建路线。

项目采用本地 FastAPI 后端、静态前端页面，以及 Google Maps / Places 相关接口。

## 1. 功能概览

- 通过 OpenAI-compatible LLM client 解析自然语言路线请求。
- 对命名目的地先做确认，再进入路线提交。
- 对 McDonald's、Starbucks、Tesco 等非唯一品牌或连锁地点展示候选位置。
- 对“我想吃点东西”“我想喝点东西”“我想给朋友买点东西”等模糊请求进行追问。
- 支持多站点路线构建。
- 支持多轮路线编辑，包括 remove、replace、insert before。
- 支持 “Find a Starbucks on the way” 这类沿当前路线追加停靠点的请求。
- 根据电量和剩余续航插入充电站。
- 支持与 baseline 版本做课程评估对比。

## 2. 系统架构

核心执行链路是：

```text
Parser -> Graph Builder -> Planner -> Tool Router -> Executor -> State Manager
```

- **Parser**：把用户输入解析成结构化 `Task`。
- **Graph Builder**：把有顺序的任务转换为线性任务图。
- **Planner**：根据任务图和当前状态决定下一步执行哪个任务。
- **Tool Router**：根据任务类型选择工具，例如 POI search 或 route planning。
- **Executor**：执行工具调用，并应用 guardrails。
- **State Manager**：维护当前任务、已完成任务、剩余任务、失败状态和 clarification 状态。

最终版本在原有 pipeline 前加入了 pre-route stage，用于处理 semantic intent classification、action-oriented route interpretation、candidate selection、clarification handling、itinerary editing 和 charging-aware augmentation。

## 3. 项目结构

```text
app/
  api/                 FastAPI routers，包括 /demo/run
  models/              Pydantic 请求、任务、图和状态模型
  services/            parser、pre-route、planner、executor、state、编辑逻辑
  tools/               Google Places POI search 和 Google Routes planning 工具
frontend/              静态 HTML、CSS、JavaScript demo UI
data/                  示例 prompts 和实验输出
docs/                  课程说明文档
scripts/               开发和 demo 辅助脚本
requirements.txt       Python 依赖
```

## 4. 运行要求

- Python 3.11+
- Google Maps / Places API key
- 兼容 OpenAI chat-completions 格式的 LLM 服务

安装依赖：

```bash
pip install -r requirements.txt
```

当前 `requirements.txt` 包括 FastAPI、Uvicorn、Pydantic、httpx、python-dotenv 和 pytest。

## 5. 环境配置

在本地创建 `.env` 文件。不要提交 `.env`，API key 应只保存在本地。

仓库里已经有 `.env.example`，可以按它作为模板。地图 demo 最重要的是：

```env
GOOGLE_MAPS_API_KEY=your_google_maps_api_key_here
```

LLM parser 还需要：

```env
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://your-openai-compatible-endpoint/v1
LLM_MODEL=your-model-name
```

其他 Google endpoint 和默认 origin 配置可以参考 `.env.example`。

## 6. 运行最终版本

在仓库根目录执行：

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

或者明确指定端口 8000：

```bash
uvicorn app.main:app --reload --port 8000
```

打开：

```text
http://127.0.0.1:8000/
```

常用后端接口：

- `GET /health`
- `POST /parse`
- `POST /demo/run`
- `GET /demo/config`

## 7. 运行 Baseline 版本

课程评估中，baseline 使用 commit `f3cff63`，代表较早的 direct-routing 版本。

创建单独 worktree：

```bash
git worktree add ../driveflow-baseline f3cff63
```

在端口 8001 运行 baseline：

```bash
cd ../driveflow-baseline
uvicorn app.main:app --reload --port 8001
```

打开：

```text
http://127.0.0.1:8001/
```

最终版本可以同时在端口 8000 运行：

```bash
cd ../driveflow-agent
uvicorn app.main:app --reload --port 8000
```

## 8. Demo 使用方式

1. 启动 FastAPI server。
2. 打开 `http://127.0.0.1:8000/`。
3. 输入 origin，或者使用 `GOOGLE_ROUTE_ORIGIN_TEXT` 配置的默认位置。
4. 输入自然语言导航请求。
5. 如果系统展示候选地点，先选择目标位置，再继续路线构建。
6. 如果系统提出 clarification question，在下一轮输入中回答。
7. 如果要做后续编辑，保持同一个浏览器会话，让前端把当前 itinerary 传回后端。

## 9. 示例 prompts

命名目的地确认：

```text
Take me to East Midlands Airport.
Go to Nottingham Castle.
Take me to the University of Manchester.
Go to Bullring Birmingham.
```

非唯一品牌候选选择：

```text
Take me to McDonald's.
Take me to Starbucks.
Take me to Tesco.
```

模糊请求追问：

```text
I want to eat something.
I want a drink.
I want to buy something for a friend.
```

多轮路线编辑：

```text
I won't be going to Nottingham Castle.
Replace McDonald's with Starbucks.
Insert Boots before the airport.
Find a Starbucks on the way.
```

充电相关测试可以输入目的地后，在页面中设置较低的 `battery_level` 和 `remaining_range_km`。

## 10. 评估设计

课程评估对比两个版本：

- **Baseline**：commit `f3cff63`，较早的 direct-routing 版本。
- **Final**：加入 pre-route disambiguation、semantic intent classification、action-oriented decisions、clarification、candidate selection、route editing 和改进后的 charging estimation。

建议重点比较：

- 命名目的地是否会先确认，而不是直接提交路线。
- 非唯一品牌是否会展示候选地点，而不是静默选择。
- 模糊请求是否能提出有效追问。
- 多轮编辑是否能正确保留并更新 itinerary。
- 低剩余续航时是否会插入充电站。

示例评估 case 在 `data/experiment_cases_example.json`。已有实验输出可以放在 `data/experiment_runs/`。

## 11. Experiment Runner

当前仓库 checkout 中没有 `scripts/experiment_runner.py`，因此无法确认一个可直接运行的 experiment runner 命令。

如果之后补充该脚本，它可以用于收集 baseline 和 final 后端的结构化响应，例如：

```bash
python3 scripts/experiment_runner.py \
  --prompt "Take me to McDonald's." \
  --case-id TC04 \
  --family "Non-unique brand" \
  --baseline-url http://127.0.0.1:8001 \
  --final-url http://127.0.0.1:8000 \
  --variants baseline,final
```

这类 runner 适合辅助收集数据，但不应完全替代人工评估。candidate card、clarification 质量和地图交互仍需要人工检查。

## 12. 已知限制

- 这是课程 demo，不是 production-ready 导航系统。
- 运行依赖 Google API 可用性和本地有效 API key。
- Parser 依赖 OpenAI-compatible LLM endpoint，不同模型可能有行为差异。
- 当前 TaskGraph 是线性的，不是完整复杂 DAG。
- Candidate selection 质量依赖 Google Places 返回结果。
- 前端把当前 itinerary 保存在浏览器会话内存中。
- 充电站插入使用的是近似距离，不是完整道路网络距离。

充电估算公式为：

```text
estimated_route_km = haversine_distance(origin, destination) x 1.25
```

这里的 haversine_distance 是两点间直线球面距离，乘以 1.25 作为轻量 road factor。它适合 demo 中做续航判断，但不等同于真实道路网络路线长度。

## 13. 课程说明

最终版本的重点不是简单调用地图工具，而是展示一个有控制流的 navigation agent：系统可以在路线提交前处理歧义、追问信息、展示候选地点，并在多轮对话中修改已有路线。

命名目的地确认策略是当前设计的一部分：East Midlands Airport、Nottingham Castle、University of Manchester、Bullring Birmingham 等命名地点，都应先解析并展示确认/候选选择，再提交导航路线。
