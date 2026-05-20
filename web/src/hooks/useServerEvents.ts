import { useEffect, useRef } from "react";
import { API_BASE_URL } from "../utils/apiClient";
import { parseServerEvent, type ServerEvent } from "../utils/appState";

const SERVER_EVENT_TYPES = [
  "chat.message.created",
  "chat.turn.started",
  "chat.turn.completed",
  "chat.turn.failed",
  "workflow_run.created",
  "workflow_run.updated",
  "workflow_run.completed",
  "workflow_run.failed",
  "workflow_run.cancelled",
  "trace.created",
  "trace.updated",
  "span.updated",
  "approval.updated",
  "dashboard.updated",
  "eval_run.created",
  "eval_run.updated",
  "eval_run.completed",
  "eval_run.failed",
];

export function useServerEvents(onEvent: (event: ServerEvent | null) => void) {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    const events = new EventSource(`${API_BASE_URL}/events`);
    const handleEvent = (rawEvent: Event) => {
      onEventRef.current(parseServerEvent(rawEvent));
    };

    events.addEventListener("message", handleEvent);
    events.addEventListener("connected", () => {});
    SERVER_EVENT_TYPES.forEach((eventType) => {
      events.addEventListener(eventType, handleEvent);
    });

    return () => events.close();
  }, []);
}
