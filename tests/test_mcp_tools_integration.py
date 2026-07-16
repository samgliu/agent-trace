import os
import unittest

from agent_apps.customer_service.runner import McpSupportToolsClient


@unittest.skipUnless(os.environ.get("AGENTTRACE_RUN_MCP_INTEGRATION"), "MCP integration test is opt-in")
class McpToolsIntegrationTest(unittest.TestCase):
    def test_mcp_support_tools_client_calls_running_fastmcp_service(self) -> None:
        client = McpSupportToolsClient(
            server_url=os.environ.get("AGENTTRACE_MCP_TOOLS_URL", "http://localhost:8010/mcp/")
        )

        customer = client.lookup_customer("customer@example.com")
        policy = client.retrieve_policy("duplicate_charge_refund")
        action = client.create_support_action("cus_123", "refund_review", "Duplicate charge detected.")

        self.assertEqual(customer["customer_id"], "cus_123")
        self.assertEqual(policy["policy_id"], "policy_refund_duplicate_charge")
        self.assertEqual(action["status"], "created")


if __name__ == "__main__":
    unittest.main()
