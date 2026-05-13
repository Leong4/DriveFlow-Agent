# DriveFlow Agent

DriveFlow Agent is a conversational navigation agent demo for an intelligent agents coursework project. It simulates an in-car assistant that turns natural language route requests into structured navigation tasks, asks for confirmation or clarification before committing to uncertain routes, and supports multi-turn itinerary changes.

The project is a local FastAPI web demo with a lightweight browser frontend and Google Maps / Places integration.

## 1. Features

- Natural language route parsing through an OpenAI-compatible LLM client.
- Pre-route confirmation for named destinations before route commitment.
- Candidate selection for non-unique brands and chain locations such as McDonald's, Starbucks, and Tesco.
- Clarification questions for vague requests such as "I want to eat something" or "I want a drink".
- Multi-stop route construction from a sequence of parsed tasks.
- Multi-turn route editing, including remove, replace, and insert-before operations.
- Along-route append behaviour for follow-up prompts such as "Find a Starbucks on the way".
- Battery/range-aware charging stop insertion.
- Baseline-vs-final evaluation support for coursework comparison.

## 2. Architecture

The core pipeline is:

```text
Parser -> Graph Builder -> Planner -> Tool Router -> Executor -> State Manager
```

- **Parser**: converts the user query into structured `Task` objects.
- **Graph Builder**: converts ordered tasks into a linear task graph.
- **Planner**: selects the next executable task from graph and state.
- **Tool Router**: maps task types to tools, such as POI search or route planning.
- **Executor**: invokes the selected tool and applies guardrails.
- **State Manager**: records current, completed, remaining, failed, and clarification states.

The final version adds a pre-route stage around the original pipeline. This stage handles semantic intent classification, action-oriented route interpretation, candidate selection, clarification handling, itinerary editing, and charging-aware augmentation before route execution.

## 3. Project Structure

```text
app/
  api/                 FastAPI routers, including /demo/run
  models/              Pydantic request, task, graph, and state models
  services/            parser, pre-route logic, planner, executor, state, editing
  tools/               Google Places POI search and Google Routes planning tools
frontend/              Static HTML, CSS, and JavaScript demo UI
data/                  Example prompts and saved experiment outputs
docs/                  Supporting coursework notes
scripts/               Development and demo helper scripts
requirements.txt       Python dependencies
```

## 4. Requirements

- Python 3.11+
- Google Maps / Places API key
- LLM provider compatible with OpenAI chat-completions format

Install dependencies:

```bash
pip install -r requirements.txt
```

The current `requirements.txt` includes FastAPI, Uvicorn, Pydantic, httpx, python-dotenv, and pytest.

## 5. Environment Configuration

Create a local `.env` file. Do not commit `.env`, and keep API keys local.

This repository includes `.env.example`; use it as a template. The most important key for the map demo is:

```env
GOOGLE_MAPS_API_KEY=your_google_maps_api_key_here
```

The LLM parser also expects:

```env
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://your-openai-compatible-endpoint/v1
LLM_MODEL=your-model-name
```

Optional Google endpoint/origin settings are shown in `.env.example`.

## 6. Running the Final Version

From the repository root:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Or explicitly run the final version on port 8000:

```bash
uvicorn app.main:app --reload --port 8000
```

Open:

```text
http://127.0.0.1:8000/
```

Useful backend endpoints:

- `GET /health`
- `POST /parse`
- `POST /demo/run`
- `GET /demo/config`

## 7. Running the Baseline Version

The coursework comparison uses commit `f3cff63` as the baseline direct-routing version.

Create a separate worktree:

```bash
git worktree add ../driveflow-baseline f3cff63
```

Run the baseline on port 8001:

```bash
cd ../driveflow-baseline
uvicorn app.main:app --reload --port 8001
```

Open:

```text
http://127.0.0.1:8001/
```

Run the final version separately on port 8000:

```bash
cd ../driveflow-agent
uvicorn app.main:app --reload --port 8000
```

## 8. How to Use the Demo

1. Start the FastAPI server.
2. Open the local frontend at `http://127.0.0.1:8000/`.
3. Enter an origin, or use the default origin configured by `GOOGLE_ROUTE_ORIGIN_TEXT`.
4. Enter a natural language navigation request.
5. If the system shows candidates, select the intended location before routing continues.
6. If the system asks a clarification question, answer it in the next turn.
7. For follow-up edits, keep using the same browser session so the frontend can send the current itinerary back to the backend.

## 9. Example Prompts

Named destinations requiring confirmation before route commitment:

```text
Take me to East Midlands Airport.
Go to Nottingham Castle.
Take me to the University of Manchester.
Go to Bullring Birmingham.
```

Non-unique brands requiring candidate selection:

```text
Take me to McDonald's.
Take me to Starbucks.
Take me to Tesco.
```

Vague requests requiring clarification:

```text
I want to eat something.
I want a drink.
I want to buy something for a friend.
```

Multi-turn route editing:

```text
I won't be going to Nottingham Castle.
Replace McDonald's with Starbucks.
Insert Boots before the airport.
Find a Starbucks on the way.
```

Charging-aware routing:

```text
Take me to East Midlands Airport.
```

Then provide low `battery_level` and `remaining_range_km` values in the demo inputs.

## 10. Evaluation Design

The evaluation compares:

- **Baseline**: earlier direct-routing version from commit `f3cff63`.
- **Final**: enhanced version with pre-route disambiguation, semantic intent classification, action-oriented decisions, clarification, candidate selection, route editing, and improved charging estimation.

Important behaviours to compare:

- Whether named destinations are confirmed before committing to a route.
- Whether non-unique brands surface candidate locations instead of silently choosing one.
- Whether vague requests trigger a useful clarification question.
- Whether follow-up route edits preserve and update the itinerary correctly.
- Whether low remaining range can insert a charging stop.

Example evaluation cases are provided in `data/experiment_cases_example.json`. Saved experiment outputs may be placed under `data/experiment_runs/`.

## 11. Experiment Runner

The requested `scripts/experiment_runner.py` file is not present in the current repository checkout. Because of that, there is no verified command for a current experiment runner script in this working tree.

If an experiment runner is added later, it should collect structured backend responses from both baseline and final servers. For example, a runner could compare:

```bash
python3 scripts/experiment_runner.py \
  --prompt "Take me to McDonald's." \
  --case-id TC04 \
  --family "Non-unique brand" \
  --baseline-url http://127.0.0.1:8001 \
  --final-url http://127.0.0.1:8000 \
  --variants baseline,final
```

Such a runner should support analysis, but it should not fully replace manual evaluation of candidate cards, clarification quality, and map behaviour.

## 12. Known Limitations

- The demo is a coursework prototype, not a production navigation system.
- It depends on Google API availability and valid local API keys.
- The parser depends on an OpenAI-compatible LLM endpoint and may vary with model behaviour.
- The task graph is currently linear rather than a full route dependency DAG.
- Candidate selection quality depends on Google Places search results.
- The frontend stores current itinerary context in browser memory during the session.
- Charging insertion uses an approximation, not full road-network distance.

Charging estimation currently uses:

```text
estimated_route_km = haversine_distance(origin, destination) x 1.25
```

This estimates road distance from straight-line distance with a road factor. It is useful for lightweight range-aware behaviour, but it is not equivalent to computing the complete road-network route distance.

## 13. Coursework Notes

The final version is designed to demonstrate agentic control flow rather than only direct tool calling. The key coursework distinction is that the system can delay route commitment when the user's request is ambiguous, ask for missing information, and modify an existing route across turns.

The named destination confirmation policy is intentional: all named destinations, including examples such as East Midlands Airport, Nottingham Castle, the University of Manchester, and Bullring Birmingham, should be resolved and confirmed before the system commits to navigation.
