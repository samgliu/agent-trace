"""Trace JSON import and normalization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agenttrace.core.models import Trace


def load_trace_file(path: Path) -> Trace:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return normalize_trace(payload)


def normalize_trace(payload: dict[str, Any]) -> Trace:
    """Normalize an OpenAI-style trace payload into AgentTrace's model."""
    return Trace.from_dict(payload)
