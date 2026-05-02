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

## Current Scope

This repository is intentionally starting small. The first goal is a reliable
trace model and CLI before adding the FastAPI backend, React dashboard, MCP
server demo, and eval harness.

## Verification

```bash
python3 -m unittest discover
python3 -m compileall agenttrace tests
```
