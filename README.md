# AgentTrace

AgentTrace is a trace operations dashboard for debugging, monitoring, and
evaluating multi-agent AI workflows.

This repo includes a real customer-service multi-agent app as the reference
workload. The dashboard observes live chat turns, Supervisor-directed handoffs,
Escalation Agent handoffs, tool calls, MCP activity, memory, approval gates,
grounding, latency, token/cost metadata, privacy redaction, and eval results.

<p align="center">
  <img src="demo/screencapture.png" alt="AgentTrace dashboard screenshot" width="680" />
</p>

## Included

- FastAPI AgentTrace API with SQLite storage.
- React/TypeScript dashboard built with Vite and pnpm.
- Standalone customer-service agent service in `agent_apps/customer_service`.
- Supervisor-led multi-agent support workflow with escalation handoff.
- FastMCP tool service for customer, policy, order, charge, and action tools.
- OpenAI-compatible model client with provider/model fallback configuration.
- OpenAI Agents-style trace import and normalization.
- SSE updates for runs, chat, traces, summaries, and eval progress.
- Deterministic and LLM-backed support-triage evals.
- Optional role-based dashboard auth with audited approval decisions.
- Default redaction for common PII in trace/span/grounding/raw responses.
- Dockerized Playwright e2e tests.

## Architecture

```text
Dashboard / Customer Service App
        |
AgentTrace API --------------- SQLite
        |
Customer-Service Agent Service
        |
Multi-Agent Orchestrator
   |-- Supervisor Agent
   |-- Triage / Policy / Action / Validator / Escalation Agents
   |-- Customer Response Generator
   |-- MCP tools
   |-- memory
   |-- approval gates
   `-- OpenAI-compatible model client
            |
      OpenAI | Gemini | gateway | local LLM
```

The agent is provider-agnostic. Real model calls use OpenAI-compatible
`/v1/chat/completions` by default, so switching providers stays in environment
configuration instead of specialist-agent logic.

## Quick Start

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

Local data is stored in `.agenttrace/agenttrace.db`.

## Demo Flow

1. Open `http://localhost:5173`.
2. Send a message in **Live customer-service agent**:

   ```text
   I was charged twice for my Pro subscription yesterday. Can I get a refund?
   ```

3. Open the generated trace and inspect the Agent Flow.
4. Run **Support agent quality** evals.
5. Review failed checks and the improvement plan.

Useful multi-turn case:

```text
I'd like to return the banana I bought last week. I ate all of them already.
```

Then:

```text
Order number: #1234
```

The agent should preserve the active issue, avoid unrelated duplicate-charge
leakage, and explain the consumed-product return boundary.

Routing case:

```text
Hello, what can you help me with?
```

This takes the direct `clarify_request` route from Supervisor to the Customer
Response Generator without unnecessary account or policy tools.

## Configuration

Each deployable service owns its own environment file:

```text
agenttrace/api/.env              # API auth, storage, agent-service URL
agent_apps/customer_service/.env # LLM provider/model/API keys and agent runtime
web/.env                         # browser-visible Vite config only
```

Use the matching `.env.example` file in each service directory as the template.
Do not put LLM keys or admin tokens in `web/.env`.

Gemini example:

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
GEMINI_FALLBACK_MODELS=gemini-2.5-flash-lite
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
AGENTTRACE_LLM_TIMEOUT_SECONDS=180
```

OpenAI-compatible gateway example:

```env
LLM_PROVIDER=openai-compatible
LLM_API_KEY=...
LLM_MODEL=...
LLM_FALLBACK_MODELS=...
LLM_BASE_URL=http://gateway.example/v1
```

After changing `.env`:

```bash
docker compose up -d --force-recreate agent-service api web
```

## Auth

Auth is disabled by default for local demos. To protect the dashboard/API, set
these in `agenttrace/api/.env`:

```env
AGENTTRACE_AUTH_ENABLED=true
AGENTTRACE_ADMIN_TOKEN=long-random-secret
AGENTTRACE_OPERATOR_TOKEN=long-random-secret
AGENTTRACE_VIEWER_TOKEN=long-random-secret
```

Then recreate the API and web containers:

```bash
docker compose up -d --force-recreate api web
```

When enabled, the dashboard shows a token login screen. The backend validates
the token once and sets an httpOnly, signed, expiring session cookie. Admin and
operator sessions can approve, reject, and revert approval gates. Viewer
sessions can read dashboards and traces but cannot mutate approvals.

Public routes: `/health`, `/auth/status`, `/auth/login`, `/auth/logout`.

## Privacy

Trace, span, grounding, and raw-payload responses redact common sensitive values
such as emails, phone numbers, and payment-like numbers by default. Redacted
responses include privacy metadata:

```text
contains_pii
redaction_applied
redaction_types
```

The dashboard displays `Privacy: Redacted` when sensitive content was masked.

## Evals

Run from the dashboard or API:

```bash
curl -X POST http://localhost:8000/evals/support-triage/run
curl -X POST 'http://localhost:8000/evals/support-triage/run?mode=llm'
curl http://localhost:8000/eval-runs/support-triage/comparison
```

Run from CLI:

```bash
python3 -m agenttrace.cli eval support-triage
python3 -m agenttrace.cli eval support-triage --mode llm
python3 -m agenttrace.cli eval support-triage --json
```

Deterministic evals are the stable baseline. LLM-backed evals measure the
configured provider/model. Provider/API failures are retained as unscored
history instead of agent-quality trend points; affected runs can be retried in
place after provider recovery without rerunning successful cases.

## CLI

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

## API

API docs are available at `http://localhost:8000/docs`.

Common endpoints:

```text
GET    /health
GET    /dashboard/summary
GET    /events

POST   /chat/sessions
POST   /chat/sessions/{session_id}/messages

POST   /workflows/support-triage/runs
GET    /workflow-runs/{run_id}
POST   /workflow-runs/{run_id}/cancel
POST   /workflow-runs/{run_id}/retry

GET    /evals
POST   /evals/support-triage/run
POST   /eval-runs/{run_id}/resume
GET    /eval-runs

GET    /traces
POST   /traces
GET    /traces/{trace_id}
GET    /traces/{trace_id}/raw
POST   /ingest/openai-agents
POST   /traces/{trace_id}/approvals/{span_id}/approve
POST   /traces/{trace_id}/approvals/{span_id}/reject
POST   /traces/{trace_id}/approvals/{span_id}/revert
```

## Development

Python:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m unittest discover
```

Frontend:

```bash
cd web
corepack pnpm install
corepack pnpm lint
corepack pnpm test
corepack pnpm build
corepack pnpm dev
```

E2E:

```bash
docker compose run --rm --build e2e
```

The Playwright report is written to `e2e/playwright-report/index.html`.

CI runs backend tests, deterministic evals, frontend tests/build, and Dockerized
Playwright e2e on pushes to `development`.

## Code Map

- `agenttrace/api/`: FastAPI app, routes, auth, eval runs, chat, approvals,
  workflow operations, SSE.
- `agenttrace/core/`: trace/span models, metrics, summary, provenance,
  redaction.
- `agenttrace/adapters/`: OpenAI Agents-style trace normalization.
- `agenttrace/storage/`: SQLite schema, row mapping, persistence.
- `agenttrace/evals/`: support-triage eval cases, reporting, assertions.
- `agent_apps/customer_service/`: multi-agent customer-service workload,
  model client, MCP/local tools, policy logic, validation, memory, trace
  construction.
- `web/src/`: React dashboard components, hooks, utilities, styles.
- `e2e/`: Dockerized Playwright product tests.
