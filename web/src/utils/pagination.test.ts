import { describe, expect, it } from "vitest";
import { clampedOffset, hasNextPage, nextOffset, pageRange, previousOffset } from "./pagination";

describe("pagination helpers", () => {
  it("moves by page size without going below zero", () => {
    expect(nextOffset(0, 50)).toBe(50);
    expect(previousOffset(50, 50)).toBe(0);
    expect(previousOffset(10, 50)).toBe(0);
  });

  it("calculates next page availability from total count", () => {
    expect(hasNextPage(0, 51, 50)).toBe(true);
    expect(hasNextPage(50, 51, 50)).toBe(false);
  });

  it("shows actual visible range for partial pages", () => {
    expect(pageRange(50, 2, 52)).toBe("51-52");
    expect(pageRange(100, 0, 52)).toBe("0-0");
  });

  it("clamps out-of-range offsets to the last valid page", () => {
    expect(clampedOffset(100, 52, 50)).toBe(50);
    expect(clampedOffset(50, 0, 50)).toBe(0);
  });
});
