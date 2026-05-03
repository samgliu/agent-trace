# AgentTrace

AgentTrace is an OpenAI Agents-compatible trace operations dashboard for
debugging, evaluating, and monitoring multi-agent AI workflows.

It currently supports:

- importing OpenAI-style trace JSON
- ingesting live traces and spans through the API
- polling live trace updates from the dashboard
- SQLite-backed trace summaries for filtering and fleet metrics
- approval gates with approve, reject, and revert actions
- grounding summaries for grounded, recovered, and failed responses
- multi-agent spans, handoffs, MCP tool calls, guardrails, and validation spans

## Quick Start

```bash
docker compose build
docker compose up -d api web
docker compose run --rm agenttrace import examples/support_triage/sample_trace.json
docker compose run --rm agenttrace import examples/support_triage/sample_trace_grounding_failure.json
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
docker compose up -d api web
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

## CLI

Import and inspect sample traces:

```bash
docker compose run --rm agenttrace import examples/support_triage/sample_trace.json
docker compose run --rm agenttrace list
docker compose run --rm agenttrace show trace_support_triage_happy_path
docker compose run --rm agenttrace show trace_support_triage_happy_path --verbose
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
GET    /dashboard/summary
GET    /workflows
GET    /traces
POST   /traces
GET    /traces/{trace_id}
PATCH  /traces/{trace_id}
POST   /traces/{trace_id}/spans
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
GET /traces?started_after=2026-05-01T00:00:00Z
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

