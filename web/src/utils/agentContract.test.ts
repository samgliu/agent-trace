import { describe, expect, it } from "vitest";
import { extractAgentContract, formatAgentContractStatus } from "./agentContract";

describe("agent contract utilities", () => {
  it("extracts normalized contract metadata from span data", () => {
    expect(
      extractAgentContract({
        agent_contract_status: "corrected",
        agent_contract: {
          status: "corrected",
          required_inputs: ["policy", "agent_state"],
          consumed_context: ["customer_memory"],
          produced_outputs: ["action_type"],
          validation_reason: "action_resolution_plan_corrected",
          corrections: ["validation_reason", "invalid_action_fields"],
        },
      }),
    ).toEqual({
      status: "corrected",
      requiredInputs: ["policy", "agent_state"],
      consumedContext: ["customer_memory"],
      producedOutputs: ["action_type"],
      validationReason: "action_resolution_plan_corrected",
      corrections: ["validation_reason", "invalid_action_fields"],
    });
  });

  it("returns null when contract metadata is absent", () => {
    expect(extractAgentContract({})).toBeNull();
  });

  it("formats statuses for display", () => {
    expect(formatAgentContractStatus("needs_review")).toBe("needs review");
  });
});
