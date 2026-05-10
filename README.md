# AgentTrace

AgentTrace is an OpenAI Agents-compatible trace operations dashboard for
debugging, evaluating, and monitoring multi-agent AI workflows.

It currently supports:

- importing OpenAI-style trace JSON
- adapting OpenAI Agents trace exports and event streams
- ingesting live traces and spans through the API
- polling live trace updates from the dashboard
- SQLite-backed trace summaries for filtering and fleet metrics
- approval gates with approve, reject, and revert actions
- grounding summaries for grounded, recovered, and failed responses
- multi-agent spans, handoffs, MCP tool calls, guardrails, and validation spans
- a FastMCP MCP-tools service used by the real workflow runner in Docker
- an executable `agent_apps/customer_service` support-triage workflow runner with optional
  OpenAI-compatible chat completions generation

## Architecture

AgentTrace treats the customer-service agent and the model provider as separate
concerns. The agent talks to a stable model client interface, and provider
routing belongs behind an OpenAI-compatible model gateway:

```text
Customer Service App / Workflow UI
        |
Multi-Agent Orchestrator
   |-- MCP tools
   |-- short-term and long-term memory
   |-- retrieval
   |-- approval gates
   `-- Model Client Interface
            |
      OpenAI-Compatible Model Gateway
            |
      Provider Adapters
        OpenAI | Anthropic | Gemini | Local LLM

AgentTrace observes the orchestrator, model calls, tool calls, retrieval,
memory, approvals, evals, latency, tokens, cost, and failures.
```

The repo currently uses deterministic mode by default for repeatable tests and
demos. Real model calls use OpenAI-compatible `/v1/chat/completions` unless the
OpenAI-native Responses API is explicitly selected. This keeps the agent code
provider-agnostic: OpenAI, Gemini, Anthropic, local vLLM, or other models should
be swapped through gateway configuration instead of custom agent branches.

## Quick Start

```bash
docker compose build
docker compose up -d api web
docker compose run --rm agenttrace import examples/support_triage/sample_trace.json
docker compose run --rm agenttrace import examples/support_triage/sample_trace_grounding_failure.json
docker compose run --rm agenttrace import examples/support_triage/sample_trace_tool_failure.json
```

Open:

```text
http://localhost:5173
http://localhost:8000/docs
```

AgentTrace stores local demo data in `.agenttrace/agenttrace.db`.

## Live Demo

Start the API and dashboard:

```bash
docker compose up -d api web mcp-tools
```

Emit a live support-triage trace into the API:

```bash
docker compose run --rm agenttrace live-sample --api-url http://api:8000 --delay 1
```

The dashboard polls every 5 seconds, so the live run appears and grows as spans
arrive. Use a smaller delay for a faster demo:

```bash
docker compose run --rm agenttrace live-sample --api-url http://api:8000 --delay 0.1
```

## MCP Tools Server

Start the FastMCP MCP-tools service:

```bash
docker compose up -d mcp-tools
```

Health check:

```text
http://localhost:8010/health
```

MCP endpoint:

```text
http://localhost:8010/mcp/
```

The server exposes deterministic support tools used by the next real workflow
runner milestone:

```text
lookup_customer_tool
retrieve_policy_tool
create_support_action_tool
```

When the stack runs through Docker Compose, the API service sets
`AGENTTRACE_MCP_TOOLS_URL=http://mcp-tools:8010/mcp/`, so
`POST /workflows/support-triage/runs` calls the MCP tools service instead of
the local in-process tool fallback.

## CLI

Import and inspect sample traces:

```bash
docker compose run --rm agenttrace import examples/support_triage/sample_trace.json
docker compose run --rm agenttrace list
docker compose run --rm agenttrace show trace_support_triage_happy_path
docker compose run --rm agenttrace show trace_support_triage_happy_path --verbose
```

Import an OpenAI Agents-style trace export:

```bash
docker compose run --rm agenttrace import examples/openai_agents/sample_trace_export.json --format openai-agents
```

For local Python development:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m agenttrace.cli import examples/support_triage/sample_trace.json
```

## API

The API is documented at:

```text
http://localhost:8000/docs
```

Core endpoints:

```text
GET    /health
POST   /chat/sessions
GET    /chat/sessions
GET    /chat/sessions/{session_id}
GET    /chat/sessions/{session_id}/messages
POST   /chat/sessions/{session_id}/messages
GET    /dashboard/summary
GET    /workflows
POST   /workflows/support-triage/runs
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
GET /traces?limit=50&offset=0
GET /traces?status=passed
GET /traces?workflow_name=support-triage
GET /traces?approval_status=pending
GET /traces?grounding_status=recovered
GET /traces?source_format=openai-agents
GET /traces?source_kind=live_api
GET /traces?has_errors=true
GET /traces?started_after=2026-05-01T00:00:00Z
```

Create a monitored customer-service chat session:

```bash
curl -X POST http://localhost:8000/chat/sessions \
  -H 'content-type: application/json' \
  -d '{
    "customer_email": "customer@example.com",
    "title": "Billing support"
  }'
```

Send a chat message. Each user message runs the support-triage agent workflow,
stores the assistant reply, and links the assistant message to the generated
trace:

```bash
curl -X POST http://localhost:8000/chat/sessions/{session_id}/messages \
  -H 'content-type: application/json' \
  -d '{
    "content": "I was charged twice for my Pro subscription yesterday. Can I get a refund?"
  }'
```

Run the executable support-triage agents workflow:

```bash
curl -X POST http://localhost:8000/workflows/support-triage/runs \
  -H 'content-type: application/json' \
  -d '{
    "trace_id": "trace_live_support_triage",
    "message": "I was charged twice for my Pro subscription yesterday. Can I get a refund?",
    "customer_email": "customer@example.com"
  }'
```

By default the workflow uses a deterministic local response generator so tests
and demos do not require credentials. To call an OpenAI-compatible model
provider or gateway for specialist agent decisions and the customer response
generation span, choose the provider and configure that provider's key/model:

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
```

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5
OPENAI_BASE_URL=https://api.openai.com/v1
```

For a gateway such as LiteLLM, OpenRouter, vLLM, or another
OpenAI-compatible proxy, use the generic fallback names:

```env
LLM_PROVIDER=openai-compatible
LLM_API_KEY=...
LLM_MODEL=...
LLM_BASE_URL=http://gateway.example/v1
```

The Docker API service reads the customer-service agent environment from
`agent_apps/customer_service/.env`. Use
`agent_apps/customer_service/.env.example` as the template and keep the real
`.env` file out of git. After changing `.env`, recreate the API container so
Compose reloads the file:

```bash
docker compose up -d --force-recreate api
```

Then send:

```json
{
  "message": "I was charged twice for my Pro subscription yesterday. Can I get a refund?",
  "customer_email": "customer@example.com",
  "use_openai": true
}
```

The default real LLM protocol is `/v1/chat/completions` because it is widely
supported by model gateways and OpenAI-compatible providers. Runtime
configuration precedence is explicit constructor args, then provider-specific
env vars, then generic `LLM_*` env vars, then legacy AgentTrace/OpenAI-compatible
env vars. OpenAI-native `/v1/responses` can be selected explicitly:

```json
{
  "message": "I was charged twice for my Pro subscription yesterday. Can I get a refund?",
  "customer_email": "customer@example.com",
  "use_openai": true,
  "openai_api": "responses"
}
```

Minimal live ingestion example:

```bash
curl -X POST http://localhost:8000/traces \
  -H 'content-type: application/json' \
  -d '{
    "trace_id": "live_trace_example",
    "workflow_name": "support-triage",
    "status": "running",
    "started_at": "2026-05-03T21:00:00Z",
    "spans": []
  }'

curl -X POST http://localhost:8000/traces/live_trace_example/spans \
  -H 'content-type: application/json' \
  -d '{
    "span_id": "span_supervisor",
    "name": "Supervisor Agent",
    "span_type": "agent",
    "started_at": "2026-05-03T21:00:00Z",
    "ended_at": "2026-05-03T21:00:01Z"
  }'

curl -X PATCH http://localhost:8000/traces/live_trace_example \
  -H 'content-type: application/json' \
  -d '{
    "status": "passed",
    "ended_at": "2026-05-03T21:00:04Z"
  }'
```

OpenAI Agents-compatible ingest:

```bash
curl -X POST http://localhost:8000/ingest/openai-agents \
  -H 'content-type: application/json' \
  --data @examples/openai_agents/sample_trace_export.json
```

The OpenAI Agents adapter supports trace-export style payloads and event-stream
style payloads. AgentTrace preserves the original source payload at
`GET /traces/{trace_id}/raw` and stores normalized spans for dashboards,
metrics, approvals, and filtering. It maps common span concepts into AgentTrace
span types:

```text
model_call      -> generation
tool_call       -> function_tool
handoff         -> handoff
guardrail       -> guardrail
custom_span     -> custom
```

Model usage fields such as `input_tokens`/`output_tokens` and
`prompt_tokens`/`completion_tokens` are normalized into AgentTrace token
metrics. Cost fields such as `estimated_cost`, `cost`, and `total_cost` are
normalized into `estimated_cost`.

## Frontend

For local frontend development:

```bash
cd web
corepack pnpm install
corepack pnpm test
corepack pnpm build
corepack pnpm dev
```

## Verification

Local checks:

```bash
python3 -m unittest discover
cd web
corepack pnpm test
corepack pnpm build
```

Docker build runs the Python and frontend checks inside images:

```bash
docker compose build
```
