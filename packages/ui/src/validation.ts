export type Validation<T> = { ok: true; value: T } | { ok: false; error: string };

const FN_NAME = /^[A-Za-z0-9_-]{1,64}$/;

function parseJson(text: string, label: string): Validation<unknown> {
  try {
    return { ok: true, value: JSON.parse(text) };
  } catch (e) {
    return { ok: false, error: `${label} is not valid JSON${e instanceof Error ? `: ${e.message}` : "."}` };
  }
}

export function validateTools(text: string): Validation<unknown[]> {
  const p = parseJson(text, "Tools");
  if (!p.ok) return p;
  if (!Array.isArray(p.value) || p.value.length === 0) return { ok: false, error: "Tools must be a non-empty JSON array." };
  const seen = new Set<string>();
  for (const [i, t] of p.value.entries()) {
    const fn = (t as { type?: unknown; function?: { name?: unknown; parameters?: unknown } } | null);
    if (!fn || typeof fn !== "object" || fn.type !== "function" || !fn.function || typeof fn.function !== "object") {
      return { ok: false, error: `Tool ${i + 1}: expected {"type":"function","function":{...}}.` };
    }
    const name = fn.function.name;
    if (typeof name !== "string" || !FN_NAME.test(name)) return { ok: false, error: `Tool ${i + 1}: function.name must be 1–64 letters, digits, underscores or dashes.` };
    if (seen.has(name)) return { ok: false, error: `Tool ${i + 1}: duplicate function name "${name}".` };
    seen.add(name);
    const params = fn.function.parameters;
    if (params !== undefined && (params === null || typeof params !== "object" || Array.isArray(params))) {
      return { ok: false, error: `Tool ${i + 1}: function.parameters must be a JSON Schema object.` };
    }
  }
  return { ok: true, value: p.value };
}

export type ToolChoiceMode = "auto" | "none" | "required" | "function";

export function buildToolChoice(mode: ToolChoiceMode, fnName: string, tools: unknown[]): Validation<unknown> {
  if (mode !== "function") return { ok: true, value: mode };
  const names = tools.map((t) => (t as { function: { name: string } }).function.name);
  if (!names.includes(fnName)) return { ok: false, error: "Choose one of the defined tool names for a forced tool choice." };
  return { ok: true, value: { type: "function", function: { name: fnName } } };
}

export function validateResponseFormat(kind: "text" | "json_object" | "json_schema", name: string, schemaText: string): Validation<unknown | undefined> {
  if (kind === "text") return { ok: true, value: undefined };
  if (kind === "json_object") return { ok: true, value: { type: "json_object" } };
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(name)) return { ok: false, error: "Schema name must be 1–64 letters, digits, underscores or dashes." };
  const p = parseJson(schemaText, "Schema");
  if (!p.ok) return p;
  if (p.value === null || typeof p.value !== "object" || Array.isArray(p.value)) return { ok: false, error: "Schema must be a JSON object." };
  return { ok: true, value: { type: "json_schema", json_schema: { name, strict: true, schema: p.value } } };
}

const TOOL_CAPS = ["tools", "tool_calling", "tool_use", "function_calling"];
const SCHEMA_CAPS = ["structured_output", "structured_outputs", "json_schema", "response_format"];

export const supportsTools = (caps: string[]) => caps.some((c) => TOOL_CAPS.includes(c.toLowerCase()));
export const supportsStructured = (caps: string[]) => caps.some((c) => SCHEMA_CAPS.includes(c.toLowerCase()));

const DECIMAL = /^\d{1,12}(\.\d{1,8})?$/;
export const isDecimal = (s: string) => DECIMAL.test(s.trim());
export const isGuid = (s: string) => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s.trim());