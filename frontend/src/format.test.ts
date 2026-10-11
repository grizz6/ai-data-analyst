import { describe, expect, it } from "vitest";
import { formatNumber, formatP, friendlyType } from "./format";

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

describe("formatNumber", () => {
  it.each([
    [9419.3548, "9,419.35"],
    [92, "92"],
    [3457.5925, "3,457.59"],
    [-0.004, "0"],
    [null, "–"],
    [undefined, "–"],
  ])("formats %s as %s", (value, expected) => {
    expect(formatNumber(value)).toBe(expected);
  });
});

describe("friendlyType", () => {
  it.each([
    ["int64", "Whole number"],
    ["Int64", "Whole number"],
    ["float64", "Number"],
    ["datetime64[ns]", "Date"],
    ["bool", "Yes / no"],
    ["object", "Text"],
    ["category", "Text"],
  ])("names %s as %s", (dtype, expected) => {
    expect(friendlyType(dtype)).toBe(expected);
  });
});
