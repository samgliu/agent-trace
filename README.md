# AgentTrace

AgentTrace is an OpenAI Agents-compatible trace analysis tool for debugging,
evaluating, and optimizing multi-agent AI workflows.

The first milestone focuses on the trace foundation:

- import OpenAI-style trace JSON
- normalize traces and spans
- store runs in SQLite
- inspect trace timelines from the CLI
- support multi-agent spans, handoffs, tool calls, guardrails, and custom spans

## Quick Start

```bash
python3 -m agenttrace.cli import examples/support_triage/sample_trace.json
python3 -m agenttrace.cli list
python3 -m agenttrace.cli show trace_support_triage_happy_path
```

By default, AgentTrace stores local data in `.agenttrace/agenttrace.db`.

## Local Environment

Use a virtual environment before adding FastAPI, MCP, or frontend tooling:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

The current foundation uses only the Python standard library, so installation is
optional for now. It becomes useful once runtime dependencies are added.

## Current Scope

This repository is intentionally starting small. The first goal is a reliable
trace model and CLI before adding the FastAPI backend, React dashboard, MCP
server demo, and eval harness.

## Verification

```bash
python3 -m unittest discover
python3 -m compileall agenttrace tests
```

## Docker

Build a local image:

```bash
docker build -t agenttrace .
```

Run CLI commands in the container:

```bash
docker run --rm agenttrace import examples/support_triage/sample_trace.json
docker run --rm agenttrace show trace_support_triage_happy_path
```

## Docker Compose

Use Compose for the local project workflow. It keeps AgentTrace state in the
repo-local `.agenttrace/` directory so imported traces persist across runs.

```bash
docker compose build
docker compose run --rm agenttrace import examples/support_triage/sample_trace.json
docker compose run --rm agenttrace list
docker compose run --rm agenttrace show trace_support_triage_happy_path
```

The initial Compose setup has one `agenttrace` service. As the project grows,
this will split into API, web, MCP, and database services.
