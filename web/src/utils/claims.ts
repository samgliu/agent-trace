export type UnsupportedClaim = {
  claim: string;
  reason?: string;
};

export function extractUnsupportedClaims(output: unknown): UnsupportedClaim[] {
  if (!output || typeof output !== "object" || Array.isArray(output)) {
    return [];
  }
  const record = output as { unsupported_claims?: unknown };
  if (!Array.isArray(record.unsupported_claims)) {
    return [];
  }
  return record.unsupported_claims
    .map((item) => {
      if (typeof item === "string") {
        return { claim: item };
      }
      if (item && typeof item === "object" && "claim" in item) {
        const claimRecord = item as { claim: unknown; reason?: unknown };
        return {
          claim: String(claimRecord.claim),
          reason: claimRecord.reason === undefined ? undefined : String(claimRecord.reason),
        };
      }
      return null;
    })
    .filter((item): item is UnsupportedClaim => item !== null);
}
