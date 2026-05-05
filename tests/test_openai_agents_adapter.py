import json
import unittest
from pathlib import Path

from agenttrace.adapters.openai_agents import normalize_openai_agents_trace
from agenttrace.core.importer import load_trace_file


class OpenAIAgentsAdapterTest(unittest.TestCase):
    def test_normalizes_trace_export(self) -> None:
        trace = load_trace_file(
            Path("examples/openai_agents/sample_trace_export.json"),
            trace_format="openai-agents",
        )

        self.assertEqual(trace.trace_id, "oa_trace_support_triage_export")
        self.assertEqual(trace.workflow_name, "support-triage")
        self.assertEqual(trace.status, "passed")
        self.assertEqual(len(trace.spans), 5)
        self.assertEqual(trace.spans[1].span_type, "generation")
        self.assertEqual(trace.spans[1].input_tokens, 620)
        self.assertEqual(trace.spans[2].span_type, "function_tool")
        self.assertEqual(trace.spans[2].name, "lookup_customer")
        self.assertEqual(trace.spans[3].span_type, "handoff")
        self.assertEqual(trace.spans[4].span_type, "guardrail")
        self.assertEqual(trace.raw_payload["id"], "oa_trace_support_triage_export")

    def test_normalizes_usage_aliases(self) -> None:
        trace = normalize_openai_agents_trace(
            {
                "id": "oa_trace_usage_aliases",
                "name": "usage-aliases",
                "spans": [
                    {
                        "id": "oa_span_model",
                        "type": "model_call",
                        "model": "gpt-5.4",
                        "usage": {
                            "prompt_tokens": 12,
                            "completion_tokens": 7,
                            "estimated_cost": 0.0003,
                        },
                    }
                ],
            }
        )

        self.assertEqual(trace.spans[0].input_tokens, 12)
        self.assertEqual(trace.spans[0].output_tokens, 7)
        self.assertEqual(trace.spans[0].estimated_cost, 0.0003)
        self.assertEqual(trace.spans[0].span_data["model"], "gpt-5.4")

    def test_normalizes_event_stream(self) -> None:
        with Path("examples/openai_agents/sample_trace_events.json").open("r", encoding="utf-8") as file:
            payload = json.load(file)

        trace = normalize_openai_agents_trace(payload)

        self.assertEqual(trace.trace_id, "oa_trace_support_triage_events")
        self.assertEqual(trace.status, "passed")
        self.assertEqual(len(trace.spans), 2)
        self.assertEqual(trace.spans[0].span_type, "agent")
        self.assertEqual(trace.spans[1].span_type, "function_tool")
        self.assertEqual(trace.spans[1].output, {"action_id": "act_123"})


if __name__ == "__main__":
    unittest.main()
