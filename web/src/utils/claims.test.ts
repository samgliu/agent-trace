import { describe, expect, it } from "vitest";
import { extractUnsupportedClaims } from "./claims";

describe("extractUnsupportedClaims", () => {
  it("extracts structured unsupported claims", () => {
    expect(
      extractUnsupportedClaims({
        unsupported_claims: [
          {
            claim: "refund your last 3 months",
            reason: "Policy requires approval",
          },
        ],
      }),
    ).toEqual([
      {
        claim: "refund your last 3 months",
        reason: "Policy requires approval",
      },
    ]);
  });

  it("supports string claims", () => {
    expect(extractUnsupportedClaims({ unsupported_claims: ["unsupported refund"] })).toEqual([
      { claim: "unsupported refund" },
    ]);
  });

  it("returns empty claims for unrelated output", () => {
    expect(extractUnsupportedClaims({ grounded: true })).toEqual([]);
  });
});
