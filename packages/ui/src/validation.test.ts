import { describe, expect, it } from "vitest";
import { buildToolChoice, isDecimal, supportsStructured, supportsTools, validateResponseFormat, validateTools } from "./validation";

describe("validation", () => {
  it("accepts valid tools and rejects bad ones", () => {
    const ok = JSON.stringify([{ type: "function", function: { name: "a_b", parameters: { type: "object" } } }]);
    expect(validateTools(ok).ok).toBe(true);
    expect(validateTools("[").ok).toBe(false);
    expect(validateTools("[]").ok).toBe(false);
    expect(validateTools('[{"type":"function","function":{"name":"bad name"}}]').ok).toBe(false);
    const dup = JSON.stringify([{ type: "function", function: { name: "a" } }, { type: "function", function: { name: "a" } }]);
    expect(validateTools(dup)).toMatchObject({ ok: false });
  });
  it("builds tool_choice", () => {
    const tools = [{ type: "function", function: { name: "a" } }];
    expect(buildToolChoice("auto", "", tools)).toEqual({ ok: true, value: "auto" });
    expect(buildToolChoice("function", "a", tools)).toMatchObject({ ok: true });
    expect(buildToolChoice("function", "z", tools).ok).toBe(false);
  });
  it("validates response formats", () => {
    expect(validateResponseFormat("text", "", "")).toEqual({ ok: true, value: undefined });
    expect(validateResponseFormat("json_schema", "r", "{}")).toMatchObject({ ok: true });
    expect(validateResponseFormat("json_schema", "r", "[]").ok).toBe(false);
    expect(validateResponseFormat("json_schema", "bad name", "{}").ok).toBe(false);
  });
  it("gates by capability and validates decimals", () => {
    expect(supportsTools(["Tools"])).toBe(true);
    expect(supportsTools([])).toBe(false);
    expect(supportsStructured(["structured_output"])).toBe(true);
    expect(isDecimal("2.50")).toBe(true);
    expect(isDecimal("-1")).toBe(false);
    expect(isDecimal("1e3")).toBe(false);
  });
});