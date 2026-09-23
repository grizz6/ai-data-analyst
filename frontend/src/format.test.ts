import { describe, expect, it } from "vitest";
import { formatP } from "./format";

describe("formatP", () => {
  it.each([
    [0, "p < 0.001"],
    [0.0004, "p < 0.001"],
    [0.001, "p = 0.001"],
    [0.0421, "p = 0.042"],
    [0.5, "p = 0.500"],
    [null, "p n/a"],
  ])("formats %s as %s", (p, expected) => {
    expect(formatP(p)).toBe(expected);
  });
});
