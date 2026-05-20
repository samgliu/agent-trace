"""Chat-session workflow helpers."""

from __future__ import annotations

import threading
from typing import Any

from agenttrace.api.agent_service import AgentServiceError, run_support_triage_agent
from agenttrace.api.event_bus import EventBus
from agenttrace.api.schemas import ChatMessageCreateRequest
from agenttrace.core.models import Trace
from agenttrace.storage.sqlite import SQLiteTraceStore


def start_async_chat_turn(
    *,
    trace_store: SQLiteTraceStore,
    event_bus: EventBus,
    session: dict[str, Any],
    previous_messages: list[dict[str, Any]],
    user_message: dict[str, Any],
    assistant_message: dict[str, Any],
    payload: ChatMessageCreateRequest,
) -> None:
    thread = threading.Thread(
        target=_complete_async_chat_turn,
        kwargs={
            "trace_store": trace_store,
            "event_bus": event_bus,
            "session": session,
            "previous_messages": previous_messages,
            "user_message": user_message,
            "assistant_message": assistant_message,
            "payload": payload,
        },
        daemon=True,
    )
    thread.start()


def with_chat_metadata(trace: Trace, *, session_id: str, user_message_id: str) -> Trace:
    metadata = dict(trace.metadata)
    metadata["chat_session_id"] = session_id
    metadata["chat_user_message_id"] = user_message_id
    return Trace(
        trace_id=trace.trace_id,
        workflow_name=trace.workflow_name,
        group_id=trace.group_id,
        status=trace.status,
        metadata=metadata,
        raw_payload=trace.raw_payload,
        started_at=trace.started_at,
        ended_at=trace.ended_at,
        spans=trace.spans,
    )


def conversation_history(messages: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    recent = messages[-limit:]
    return [
        {
            "role": message["role"],
            "content": message["content"],
            "trace_id": message.get("trace_id"),
            "event_type": message.get("metadata", {}).get("event_type"),
        }
        for message in recent
    ]


def assistant_response_from_trace(trace: Trace) -> str:
    for span in reversed(trace.spans):
        if span.span_type != "generation":
            continue
        if isinstance(span.output, dict) and span.output.get("response"):
            return str(span.output["response"])
    if trace.status == "failed":
        return "I could not complete that support workflow. A support specialist should review this request."
    return "I reviewed the request and created the next support action."


def _complete_async_chat_turn(
    *,
    trace_store: SQLiteTraceStore,
    event_bus: EventBus,
    session: dict[str, Any],
    previous_messages: list[dict[str, Any]],
    user_message: dict[str, Any],
    assistant_message: dict[str, Any],
    payload: ChatMessageCreateRequest,
) -> None:
    try:
        trace = run_support_triage_agent(
            message=payload.content,
            customer_email=session["customer_email"],
            trace_id=f"trace_chat_{user_message['message_id']}",
            conversation_history=conversation_history(previous_messages),
            use_openai=payload.use_openai,
            openai_api=payload.openai_api,
        )
        trace = with_chat_metadata(trace, session_id=session["session_id"], user_message_id=user_message["message_id"])
        trace_store.save_trace(trace)
        _publish_trace_events(event_bus, "trace.created", trace.trace_id, session_id=session["session_id"])
        saved_trace = _require_trace(trace_store, trace.trace_id)
        trace_store.update_chat_message(
            assistant_message["message_id"],
            content=assistant_response_from_trace(saved_trace),
            trace_id=saved_trace.trace_id,
            metadata={
                "status": "complete",
                "pending": False,
                "trace_status": saved_trace.status,
                "chat_user_message_id": user_message["message_id"],
            },
        )
        event_bus.publish(
            "chat.turn.completed",
            resource_type="chat_session",
            resource_id=session["session_id"],
            session_id=session["session_id"],
            trace_id=saved_trace.trace_id,
        )
    except AgentServiceError as exc:
        _mark_async_chat_failed(trace_store, event_bus, session, assistant_message, user_message, exc.message)
    except RuntimeError as exc:
        _mark_async_chat_failed(trace_store, event_bus, session, assistant_message, user_message, str(exc))


def _mark_async_chat_failed(
    trace_store: SQLiteTraceStore,
    event_bus: EventBus,
    session: dict[str, Any],
    assistant_message: dict[str, Any],
    user_message: dict[str, Any],
    message: str,
) -> None:
    trace_store.update_chat_message(
        assistant_message["message_id"],
        content=message,
        metadata={
            "status": "failed",
            "pending": False,
            "error": message,
            "chat_user_message_id": user_message["message_id"],
        },
    )
    event_bus.publish(
        "chat.turn.failed",
        resource_type="chat_session",
        resource_id=session["session_id"],
        session_id=session["session_id"],
        message=message,
    )


def _require_trace(store: SQLiteTraceStore, trace_id: str) -> Trace:
    trace = store.get_trace(trace_id)
    if trace is None:
        raise RuntimeError(f"Trace not found after chat run: {trace_id}")
    return trace


def _publish_trace_events(event_bus: EventBus, event_type: str, trace_id: str, **extra: Any) -> None:
    event_bus.publish(event_type, resource_type="trace", resource_id=trace_id, trace_id=trace_id, **extra)
    event_bus.publish("dashboard.updated", resource_type="dashboard", resource_id="summary")
