# AgentTrace

AgentTrace is an OpenAI Agents-compatible trace operations dashboard for
debugging, monitoring, and evaluating multi-agent AI workflows.

CI for this repo runs on pushes to `development`, which covers merges into the
development branch with backend tests, deterministic evals, frontend
tests/build, and Dockerized Playwright e2e.

The repo includes a monitored customer-service agent as the reference workload.
Each chat turn or workflow run emits traces with agent spans, handoffs, MCP tool
calls, retrieval, memory reads/writes, guardrails, approval gates, token/cost
metadata, and eval results.

## What It Demonstrates

- Trace ingestion for AgentTrace JSON and OpenAI Agents-style exports/events.
- A Dockerized AgentTrace API, standalone agent service, React dashboard,
  SQLite store, and FastMCP tool service.
- A customer-service multi-agent workflow under `agent_apps/customer_service`.
- Live workflow execution with SSE invalidation, cancellation, retry, and
  trace lifecycle tracking.
- A live chat monitor where each customer message generates a trace.
- An Agent Flow view that highlights supervisor, specialist, validator, and
  response-generator steps in a multi-agent run.
- Approval gates with approve, reject, and revert actions.
- Grounding, memory, cost, latency, source, and error summaries.
- A deterministic eval suite covering routing, policy selection,
  response quality, memory health, leakage checks, abuse-risk review, account
  mismatch, and multi-turn continuity.
- Dockerized Playwright e2e checks for the dashboard, live chat SSE, approval
  actions, filtering, empty states, pagination, and SSE-driven runs refresh.
- Optional OpenAI-compatible model calls through provider/gateway environment
  configuration.

## Architecture

AgentTrace keeps the agent workflow, observability backend, tool boundary, and
model provider separate:

```text
Customer Service App / Chat UI
        |
Customer-Service Agent Service
        |
Multi-Agent Orchestrator
   |-- MCP tools
   |-- short-term and long-term memory
   |-- policy retrieval
   |-- approval gates
   `-- Model Client Interface
            |
      OpenAI-Compatible Model Gateway
            |
      Provider Adapters
        OpenAI | Gemini | Anthropic | Local LLM

        |
AgentTrace API

AgentTrace observes traces, spans, model calls, tool calls, retrieval, memory,
approvals, evals, latency, tokens, cost, and failures. The agent service can be
called directly by other services without going through the dashboard.
```

Deterministic mode is the default so tests and demos are repeatable without API
keys. Real model calls use OpenAI-compatible `/v1/chat/completions` by default,
which works with OpenAI, Gemini's OpenAI-compatible endpoint, LiteLLM,
OpenRouter, local vLLM, and similar gateways.

## Quick Start

Start the full local stack:

```bash
docker compose up -d --build api web agent-service mcp-tools
```

Open:

```text
Dashboard: http://localhost:5173
API docs:  http://localhost:8000/docs
Agent:     http://localhost:8020/health
MCP tools: http://localhost:8010/health
```

AgentTrace stores local data in `.agenttrace/agenttrace.db`.

Run the Dockerized browser e2e suite:

```bash
docker compose run --rm --build e2e
```

The Playwright HTML report is written to:

```text
e2e/playwright-report/index.html
```

Current e2e coverage includes:

- dashboard smoke/load
- live customer-service chat completion through real SSE
- generated chat trace selection and inspection
- approval approve/reject/revert
- Runs Inbox approval filtering and empty-state reset
- Runs Inbox pagination at 25 traces per page
- SSE refresh after a trace is ingested
- Agent Flow rendering and timeline focus behavior
- eval dashboard running progress, partial result detail, and model fallback display

Import demo traces:

```bash
docker compose run --rm agenttrace import examples/support_triage/sample_trace.json
docker compose run --rm agenttrace import examples/support_triage/sample_trace_grounding_failure.json
docker compose run --rm agenttrace import examples/support_triage/sample_trace_tool_failure.json
```

## Demo Flow

Use this flow for a concise project demo:

1. Open `http://localhost:5173`.
2. Use **Live customer-service agent** to send a message such as:

   ```text
   I was charged twice for my Pro subscription yesterday. Can I get a refund?
   ```

3. Open the generated trace from the chat message.
4. Inspect the multi-agent timeline:
   - Supervisor Agent
   - Triage Agent
   - MCP customer lookup
   - Policy Agent and retrieval
   - Action Agent
   - Validator Agent
   - Customer Response Generator
5. Run evals from **Support agent quality**.
6. Review category counts for routing, policy, memory, response quality, and
   reliability.
7. Try a multi-turn case:

   ```text
   I'd like to return the banana I bought last week. I ate all of them already.
   ```

   Follow up with:

   ```text
   Order number: #1234
   ```

The agent should keep the active issue, avoid unrelated duplicate-charge
leakage, and explain the consumed-product return boundary.

## Customer-Service Agent

The reference agent lives in:

```text
agent_apps/customer_service/
```

It models a production-style support workflow:

- Supervisor Agent coordinates the run.
- Triage Agent classifies the current issue and preserves follow-up context.
- Policy Agent selects the policy retrieval topic.
- Action Agent chooses the next support action.
- Validator Agent checks grounding, approval requirements, and abuse-risk
  controls.
- Customer Response Generator writes the final customer-facing reply.

The standalone agent service runs at:

```text
http://localhost:8020
```

Direct run endpoint:

```text
POST /runs/support-triage
```

The AgentTrace API delegates chat/workflow execution to this service in Docker
through:

```text
AGENTTRACE_AGENT_SERVICE_URL=http://agent-service:8020
```

The agent service uses the FastMCP tools service through:

```text
AGENTTRACE_MCP_TOOLS_URL=http://mcp-tools:8010/mcp/
```

Available MCP tools:

```text
lookup_customer_tool
retrieve_policy_tool
lookup_order_tool
lookup_charge_tool
verify_order_owner_tool
create_support_action_tool
create_refund_review_tool
create_quality_exception_review_tool
```

## Evals

Run the eval suite from the dashboard or API:

```bash
curl -X POST http://localhost:8000/evals/support-triage/run
curl -X POST 'http://localhost:8000/evals/support-triage/run?mode=llm'
curl http://localhost:8000/eval-runs/support-triage/comparison
```

Run the same suite as a CI-friendly local report:

```bash
python3 -m agenttrace.cli eval support-triage
python3 -m agenttrace.cli eval support-triage --mode llm
python3 -m agenttrace.cli eval support-triage --json
```

The CLI returns a non-zero exit code when eval checks fail. Use `--no-fail` if
you want report-only behavior.

Deterministic mode is the stable baseline for CI and local regression checks.
LLM mode runs the same cases through the configured provider/model so real agent
behavior can be evaluated separately from the simulation baseline.
From the dashboard, LLM evals run asynchronously and update through SSE so a
slow provider does not block the UI request.
The comparison endpoint pairs the latest deterministic and LLM-backed runs and
highlights LLM regressions, improvements, shared failures, and pass-rate delta.

The current suite has 11 cases, including:

- duplicate-charge refund
- annual refund approval
- stale subscription refund approval
- unknown customer clarification
- lookup timeout failure
- consumed-product return boundary
- consumed-product follow-up continuity
- explicit topic switch
- quality/safety exception
- repeated-refund abuse review
- account mismatch clarification

Eval checks include trace status, issue type, policy ID, action type, approval
requirement, grounding status, memory warning count, error count, required
response text, and disallowed response text.

Eval runs are saved in SQLite and linked to generated traces for dashboard
drilldown.

### Eval-to-Agent Improvement Loop

Use failed evals as the main workflow for improving the customer-service agent:

1. Run the deterministic suite first to check stable regressions.
2. Run the LLM-backed suite to measure the configured provider/model.
3. Open failed cases in the dashboard and inspect Agent Flow, failed spans, raw
   model output, grounding, approvals, memory, and tool evidence.
4. Use `python3 -m agenttrace.cli eval support-triage --json` to get the
   `improvement_plan`, which groups failures by owner area and suggested files.
5. Patch the smallest prompt, domain rule, tool path, memory behavior, or
   guardrail that explains the failure.
6. Add or update a focused eval/unit test for that behavior.
7. Re-run deterministic and LLM evals before merging.

## Model Provider Configuration

By default, the agent uses deterministic local generation.

For real model calls, create:

```text
agent_apps/customer_service/.env
```

Use `agent_apps/customer_service/.env.example` as the template.

Gemini through its OpenAI-compatible endpoint:

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
GEMINI_FALLBACK_MODELS=gemini-2.5-flash-lite
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
```

OpenAI:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5
OPENAI_BASE_URL=https://api.openai.com/v1
```

Generic gateway:

```env
LLM_PROVIDER=openai-compatible
LLM_API_KEY=...
LLM_MODEL=...
LLM_FALLBACK_MODELS=...
LLM_BASE_URL=http://gateway.example/v1
```

Fallback models are comma-separated and tried only for provider capacity errors
such as HTTP 429, 503, or 529. Provider-specific fallback variables, such as
`GEMINI_FALLBACK_MODELS`, take precedence over `LLM_FALLBACK_MODELS`.
Trace spans record the selected model, model attempts, and whether fallback was
used, so LLM-backed evals and chat runs can explain provider capacity behavior.

After changing `.env`, recreate the agent service and API containers:

```bash
docker compose up -d --force-recreate agent-service api
```

Set `use_openai: true` on workflow or chat requests to use the configured
provider. The default real-model protocol is `/v1/chat/completions`; the
OpenAI-native `/v1/responses` path can be selected with `openai_api:
"responses"` where supported.

## CLI

Import and inspect traces:

```bash
docker compose run --rm agenttrace import examples/support_triage/sample_trace.json
docker compose run --rm agenttrace list
docker compose run --rm agenttrace show trace_support_triage_happy_path
docker compose run --rm agenttrace show trace_support_triage_happy_path --verbose
```

Import an OpenAI Agents-style export:

```bash
docker compose run --rm agenttrace import examples/openai_agents/sample_trace_export.json --format openai-agents
```

Emit a live sample trace:

```bash
docker compose run --rm agenttrace live-sample --api-url http://api:8000 --delay 0.1
```

## API Surface

API docs are available at:

```text
http://localhost:8000/docs
```

Common endpoints:

```text
GET    /health
GET    /dashboard/summary
GET    /workflows

POST   /chat/sessions
GET    /chat/sessions
GET    /chat/sessions/{session_id}
POST   /chat/sessions/{session_id}/messages
POST   /chat/sessions/{session_id}/messages/async
GET    /events

POST   /workflows/support-triage/runs
POST   /workflows/support-triage/runs/live
GET    /workflow-runs/{run_id}
POST   /workflow-runs/{run_id}/cancel
POST   /workflow-runs/{run_id}/retry

GET    /evals
POST   /evals/support-triage/run
GET    /eval-runs
GET    /eval-runs/{run_id}

GET    /traces
POST   /traces
GET    /traces/{trace_id}
GET    /traces/{trace_id}/raw
PATCH  /traces/{trace_id}
POST   /traces/{trace_id}/spans
POST   /ingest/openai-agents
GET    /traces/{trace_id}/metrics
GET    /traces/{trace_id}/grounding
POST   /traces/{trace_id}/approvals/{span_id}/approve
POST   /traces/{trace_id}/approvals/{span_id}/reject
POST   /traces/{trace_id}/approvals/{span_id}/revert
```

Trace list filters:

```text
GET /traces?limit=25&offset=0
GET /traces?workflow_name=support-triage
GET /traces?status=passed
GET /traces?approval_status=pending
GET /traces?grounding_status=recovered
GET /traces?source_format=openai-agents
GET /traces?source_kind=eval_run
GET /traces?has_errors=true
```

## OpenAI Agents Compatibility

AgentTrace can ingest OpenAI Agents-style trace exports and event streams:

```bash
curl -X POST http://localhost:8000/ingest/openai-agents \
  -H 'content-type: application/json' \
  --data @examples/openai_agents/sample_trace_export.json
```

The adapter preserves the raw source payload at:

```text
GET /traces/{trace_id}/raw
```

It normalizes common span concepts:

```text
model_call      -> generation
tool_call       -> function_tool
handoff         -> handoff
guardrail       -> guardrail
custom_span     -> custom
```

Token fields such as `input_tokens`, `output_tokens`, `prompt_tokens`, and
`completion_tokens` are normalized into AgentTrace token metrics. Cost fields
such as `estimated_cost`, `cost`, and `total_cost` are normalized into
`estimated_cost`.

## Local Development

Python:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m unittest discover tests
```

Frontend:

```bash
cd web
corepack pnpm install
corepack pnpm test
corepack pnpm build
corepack pnpm dev
```

Docker build runs backend and frontend tests inside images:

```bash
docker compose build
```

End-to-end integration checks:

```bash
docker compose run --rm --build e2e
```

GitHub Actions runs backend tests, deterministic evals, frontend tests/build,
and Dockerized Playwright e2e after changes are merged into `development`.
