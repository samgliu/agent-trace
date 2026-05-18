import io
import json
import unittest
from contextlib import redirect_stdout

from agenttrace.cli import main


class CliTest(unittest.TestCase):
    def test_eval_support_triage_prints_ci_report(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = main(["eval", "support-triage"])

        self.assertEqual(exit_code, 0)
        self.assertIn("Eval suite: Support triage core", output.getvalue())
        self.assertIn("Mode: deterministic", output.getvalue())
        self.assertIn("Status: passed", output.getvalue())
        self.assertIn("Cases: 11/11 passed", output.getvalue())

    def test_eval_support_triage_json_report(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = main(["eval", "support-triage", "--json"])

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["suite_id"], "support-triage-core")
        self.assertEqual(payload["execution_mode"], "deterministic")
        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["failed_cases"], [])
        self.assertEqual(payload["improvement_plan"], [])


if __name__ == "__main__":
    unittest.main()
