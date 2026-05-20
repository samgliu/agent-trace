"""Chat route registration."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException

from agenttrace.api.event_bus import EventBus
from agenttrace.api.schemas import ChatMessageCreateRequest, ChatSessionCreateRequest
from agenttrace.core.models import Trace
from agenttrace.storage.sqlite import SQLiteTraceStore

RunSupportTriageAgent = Callable[..., Trace]
RequireChatSession = Callable[[SQLiteTraceStore, str], dict[str, Any]]
RequireTrace = Callable[[SQLiteTraceStore, str], Trace]
WithChatMetadata = Callable[..., Trace]
PublishTraceEvents = Callable[..., None]
AssistantResponseFromTrace = Callable[[Trace], str]
ConversationHistory = Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
StartAsyncChatTurn = Callable[..., None]


def register_chat_routes(
    app: FastAPI,
    *,
    trace_store: SQLiteTraceStore,
    event_bus: EventBus,
    require_chat_session: RequireChatSession,
    require_trace: RequireTrace,
    run_support_triage_agent: RunSupportTriageAgent,
    with_chat_metadata: WithChatMetadata,
    publish_trace_events: PublishTraceEvents,
    assistant_response_from_trace: AssistantResponseFromTrace,
    conversation_history: ConversationHistory,
    start_async_chat_turn: StartAsyncChatTurn,
) -> None:
    @app.post("/chat/sessions")
    def create_chat_session(payload: ChatSessionCreateRequest) -> dict[str, Any]:
        session = trace_store.create_chat_session(
            customer_email=payload.customer_email,
            title=payload.title,
            metadata=payload.metadata,
        )
        return {**session, "messages": []}

    @app.get("/chat/sessions")
    def list_chat_sessions() -> list[dict[str, Any]]:
        return trace_store.list_chat_sessions()

    @app.get("/chat/sessions/{session_id}")
    def get_chat_session(session_id: str) -> dict[str, Any]:
        session = require_chat_session(trace_store, session_id)
        return {**session, "messages": trace_store.list_chat_messages(session_id)}

    @app.get("/chat/sessions/{session_id}/messages")
    def list_chat_messages(session_id: str) -> list[dict[str, Any]]:
        require_chat_session(trace_store, session_id)
        return trace_store.list_chat_messages(session_id)

    @app.post("/chat/sessions/{session_id}/messages")
    def create_chat_message(session_id: str, payload: ChatMessageCreateRequest) -> dict[str, Any]:
        session = require_chat_session(trace_store, session_id)
        previous_messages = trace_store.list_chat_messages(session_id)
        user_message = trace_store.add_chat_message(
            session_id,
            role="user",
            content=payload.content,
        )
        try:
            trace = run_support_triage_agent(
                message=payload.content,
                customer_email=session["customer_email"],
                trace_id=f"trace_chat_{user_message['message_id']}",
                conversation_history=conversation_history(previous_messages),
                use_openai=payload.use_openai,
                openai_api=payload.openai_api,
            )
        except RuntimeError as exc:
            raise _http_exception_from_runtime_error(exc) from exc
        trace = with_chat_metadata(trace, session_id=session_id, user_message_id=user_message["message_id"])
        trace_store.save_trace(trace)
        publish_trace_events(event_bus, "trace.created", trace.trace_id, session_id=session_id)
        saved_trace = require_trace(trace_store, trace.trace_id)
        assistant_message = trace_store.add_chat_message(
            session_id,
            role="assistant",
            content=assistant_response_from_trace(saved_trace),
            trace_id=saved_trace.trace_id,
            metadata={"trace_status": saved_trace.status},
        )
        event_bus.publish(
            "chat.turn.completed",
            resource_type="chat_session",
            resource_id=session_id,
            session_id=session_id,
            trace_id=saved_trace.trace_id,
        )
        return {
            "session": require_chat_session(trace_store, session_id),
            "user_message": user_message,
            "assistant_message": assistant_message,
            "trace": saved_trace.to_dict(),
        }

    @app.post("/chat/sessions/{session_id}/messages/async")
    def create_async_chat_message(session_id: str, payload: ChatMessageCreateRequest) -> dict[str, Any]:
        session = require_chat_session(trace_store, session_id)
        previous_messages = trace_store.list_chat_messages(session_id)
        user_message = trace_store.add_chat_message(
            session_id,
            role="user",
            content=payload.content,
        )
        assistant_message = trace_store.add_chat_message(
            session_id,
            role="assistant",
            content="Checking account, policy, and approval context",
            metadata={
                "status": "pending",
                "pending": True,
                "chat_user_message_id": user_message["message_id"],
            },
        )
        event_bus.publish(
            "chat.turn.started",
            resource_type="chat_session",
            resource_id=session_id,
            session_id=session_id,
        )
        start_async_chat_turn(
            trace_store=trace_store,
            event_bus=event_bus,
            session=session,
            previous_messages=previous_messages,
            user_message=user_message,
            assistant_message=assistant_message,
            payload=payload,
        )
        return {
            "session": require_chat_session(trace_store, session_id),
            "user_message": user_message,
            "assistant_message": assistant_message,
        }


def _http_exception_from_runtime_error(exc: RuntimeError) -> HTTPException:
    return HTTPException(
        status_code=int(getattr(exc, "status_code", 400)),
        detail=str(getattr(exc, "message", str(exc))),
    )
