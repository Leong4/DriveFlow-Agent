# DriveFlow Agent

## Overview
DriveFlow Agent is an agent-oriented task planning system for conversational navigation. It converts complex natural language navigation requests into structured tasks and executes them through tool orchestration. The system focuses heavily on agent system architecture.

## System Architecture
**Pipeline:**
User Input → Intent Parser → Task Graph Builder → Task Planner → Tool Router → Executor → State Manager

## Project Structure
- `app/api/`: FastAPI routes and endpoints.
- `app/core/`: Core configurations, logging, and setup.
- `app/models/`: Pydantic data models.
- `app/services/`: Business logic and external service integrations.
- `app/tools/`: Agent tool definitions.
- `app/executor/`: Core agent execution and state management.
- `tests/`: Unit and integration tests (pytest).
- `scripts/`: Evaluation and utility scripts.
- `data/`: Local data and samples.
- `docs/`: Project documentation.

## Tech Stack
- **Language:** Python 3.11+
- **Backend:** FastAPI
- **Data Model:** Pydantic
- **LLM:** OpenAI-compatible API (Qwen / OpenRouter / OpenAI)
- **Maps API:** Google Maps API or Amap
- **Speech Recognition:** OpenAI Whisper
- **UI:** Streamlit (minimal demo)
- **Testing:** pytest
- **HTTP client:** httpx
- **Environment:** python-dotenv

## Development Plan
- **Week1:** Intent Parsing
- **Week2:** Task Graph + Planner
- **Week3:** Tool Execution
- **Week4:** ASR + UI + Evaluation

## Future Work
- Multi-agent architecture
- Complex frontend animation
- Streaming voice processing
- On-device deployment
- Generic agent framework
