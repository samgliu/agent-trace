"""Trace JSON import and normalization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agenttrace.adapters.openai_agents import normalize_openai_agents_trace
from agenttrace.core.models import Trace


def load_trace_file(path: Path, *, trace_format: str = "agenttrace") -> Trace:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return normalize_trace(payload, trace_format=trace_format)


def normalize_trace(payload: dict[str, Any], *, trace_format: str = "agenttrace") -> Trace:
    """Normalize an OpenAI-style trace payload into AgentTrace's model."""
    if trace_format == "openai-agents":
        return normalize_openai_agents_trace(payload)
    return Trace.from_dict(payload)
