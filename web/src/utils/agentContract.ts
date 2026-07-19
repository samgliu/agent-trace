export type AgentContractStatus = "passed" | "corrected" | "failed" | string;

export type AgentContract = {
  status: AgentContractStatus;
  requiredInputs: string[];
  consumedContext: string[];
  producedOutputs: string[];
  validationReason: string | null;
  corrections: string[];
};

export function extractAgentContract(spanData: Record<string, unknown>): AgentContract | null {
  const contract = objectValue(spanData.agent_contract);
  const status = stringValue(contract?.status) ?? stringValue(spanData.agent_contract_status);
  if (!contract || !status) {
    return null;
  }
  return {
    status,
    requiredInputs: stringArray(contract.required_inputs),
    consumedContext: stringArray(contract.consumed_context),
    producedOutputs: stringArray(contract.produced_outputs),
    validationReason: stringValue(contract.validation_reason),
    corrections: stringArray(contract.corrections),
  };
}

export function formatAgentContractStatus(status: AgentContractStatus): string {
  return status.replaceAll("_", " ");
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}
