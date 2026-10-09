import { SseParser } from "./sse";

export type ChatMessage =
  | { role: "system" | "user"; content: string }
  | { role: "assistant"; content: string | null; tool_calls?: unknown[] };

export interface ChatRequest {
  model: string;
  messages: ChatMessage[];
  tools?: unknown[];
  tool_choice?: unknown;
  response_format?: unknown;
}

export interface ProposedToolCall {
  index: number;
  id: string;
  name: string;
  arguments: string;
}

export interface ChatUsage {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  [k: string]: unknown;
}

export type ChatOutcome =
  | "streaming"
  | "completed" // normal finish_reason (stop / tool_calls / function_call) and [DONE]
  | "length" // finish_reason length: model output limit reached
  | "content_filter" // server explicitly reported finish_reason content_filter
  | "provider_error" // error frame / error body from the server
  | "http_error" // non-2xx before streaming
  | "abnormal" // stream ended without [DONE] or finish_reason
  | "cancelled" // user aborted
  | "network_error";

export interface ChatResult {
  outcome: ChatOutcome;
  content: string;
  toolCalls: ProposedToolCall[];
  finishReason: string | null;
  usage: ChatUsage | null;
  errorMessage?: string;
  httpStatus?: number;
  retryAfter?: string | null;
  sawDone: boolean;
}

export function emptyResult(): ChatResult {
  return { outcome: "streaming", content: "", toolCalls: [], finishReason: null, usage: null, sawDone: false };
}

interface Delta {
  content?: string | null;
  tool_calls?: { index?: number; id?: string; function?: { name?: string; arguments?: string } }[];
}

/** Accumulates streamed chat.completion.chunk frames. */
export class ChatAccumulator {
  result: ChatResult = emptyResult();
  private tools = new Map<number, ProposedToolCall>();

  /** Returns true when the frame changed visible state. */
  frame(data: string): boolean {
    if (data.trim() === "[DONE]") {
      this.result.sawDone = true;
      return true;
    }
    let obj: unknown;
    try {
      obj = JSON.parse(data);
    } catch {
      this.result.outcome = "provider_error";
      this.result.errorMessage = "Received a malformed (non-JSON) stream frame.";
      return true;
    }
    if (!obj || typeof obj !== "object") return false;
    const o = obj as Record<string, unknown>;
    if (o.error) {
      this.result.outcome = "provider_error";
      const e = o.error as { message?: unknown };
      this.result.errorMessage = typeof e === "string" ? e : typeof e?.message === "string" ? e.message : "The server reported an error during the stream.";
      return true;
    }
    let changed = false;
    if (o.usage && typeof o.usage === "object") {
      this.result.usage = o.usage as ChatUsage;
      changed = true;
    }
    const choices = Array.isArray(o.choices) ? (o.choices as Record<string, unknown>[]) : [];
    const choice = choices[0];
    if (choice) {
      const delta = (choice.delta ?? {}) as Delta;
      if (typeof delta.content === "string" && delta.content) {
        this.result.content += delta.content;
        changed = true;
      }
      for (const tc of delta.tool_calls ?? []) {
        const idx = typeof tc.index === "number" ? tc.index : 0;
        const cur = this.tools.get(idx) ?? { index: idx, id: "", name: "", arguments: "" };
        if (tc.id) cur.id = tc.id;
        if (tc.function?.name) cur.name += tc.function.name;
        if (tc.function?.arguments) cur.arguments += tc.function.arguments;
        this.tools.set(idx, cur);
        changed = true;
      }
      if (typeof choice.finish_reason === "string") {
        this.result.finishReason = choice.finish_reason;
        changed = true;
      }
      this.result.toolCalls = [...this.tools.values()].sort((a, b) => a.index - b.index);
    }
    return changed;
  }

  /** Decide the final outcome once the transport has ended normally. */
  finalize(): ChatResult {
    const r = this.result;
    if (r.outcome === "provider_error") return r;
    const fr = r.finishReason;
    if (fr === "content_filter") r.outcome = "content_filter";
    else if (!r.sawDone || !fr) {
      r.outcome = "abnormal";
      r.errorMessage = r.sawDone
        ? "The stream ended without a finish reason. The response may be incomplete."
        : "The stream ended before the server sent [DONE]. The response is truncated or incomplete; it was not retried.";
    } else if (fr === "length") r.outcome = "length";
    else r.outcome = "completed";
    return r;
  }
}

export interface StreamOptions {
  gatewayUrl: string;
  key: string;
  request: ChatRequest;
  stream: boolean;
  signal?: AbortSignal;
  onUpdate?: (r: ChatResult) => void;
  fetchImpl?: typeof fetch;
}

function errorFromBody(text: string, status: number): string {
  try {
    const b = JSON.parse(text) as { error?: { message?: string } | string; detail?: string; message?: string };
    if (typeof b.error === "string") return b.error;
    if (b.error?.message) return b.error.message;
    if (b.detail) return b.detail;
    if (b.message) return b.message;
  } catch {
    /* ignore */
  }
  return `The gateway returned HTTP ${status}.`;
}

/** Direct gateway call. No retries: a failed or interrupted call is reported, never replayed. */
export async function chatCompletion(opts: StreamOptions): Promise<ChatResult> {
  const fetchImpl = opts.fetchImpl ?? ((...a: Parameters<typeof fetch>) => fetch(...a));
  const body: Record<string, unknown> = { ...opts.request, stream: opts.stream };
  if (opts.stream) body.stream_options = { include_usage: true };
  const acc = new ChatAccumulator();
  const emit = () => opts.onUpdate?.({ ...acc.result, toolCalls: [...acc.result.toolCalls] });

  let res: Response;
  try {
    res = await fetchImpl(`${opts.gatewayUrl}/chat/completions`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${opts.key}`,
        "Content-Type": "application/json",
        Accept: opts.stream ? "text/event-stream" : "application/json",
      },
      body: JSON.stringify(body),
      cache: "no-store",
      credentials: "omit",
      referrerPolicy: "no-referrer",
      signal: opts.signal,
    });
  } catch (e) {
    if (opts.signal?.aborted || (e instanceof DOMException && e.name === "AbortError")) {
      acc.result.outcome = "cancelled";
    } else {
      acc.result.outcome = "network_error";
      acc.result.errorMessage = "Could not reach the gateway. The request was not retried.";
    }
    return acc.result;
  }

  if (!res.ok) {
    let text = "";
    try {
      text = await res.text();
    } catch {
      /* ignore */
    }
    acc.result.outcome = "http_error";
    acc.result.httpStatus = res.status;
    acc.result.retryAfter = res.headers.get("Retry-After");
    acc.result.errorMessage = errorFromBody(text, res.status);
    return acc.result;
  }

  if (!opts.stream) {
    try {
      const json = (await res.json()) as { choices?: { message?: { content?: string | null; tool_calls?: { id?: string; function?: { name?: string; arguments?: string } }[] }; finish_reason?: string }[]; usage?: ChatUsage; error?: { message?: string } };
      if (json.error) {
        acc.result.outcome = "provider_error";
        acc.result.errorMessage = json.error.message ?? "The server reported an error.";
        return acc.result;
      }
      const c = json.choices?.[0];
      acc.result.content = c?.message?.content ?? "";
      acc.result.toolCalls = (c?.message?.tool_calls ?? []).map((t, i) => ({ index: i, id: t.id ?? "", name: t.function?.name ?? "", arguments: t.function?.arguments ?? "" }));
      acc.result.finishReason = c?.finish_reason ?? null;
      acc.result.usage = json.usage ?? null;
      acc.result.sawDone = true;
      const done = acc.finalize();
      emit();
      return done;
    } catch (e) {
      if (opts.signal?.aborted) acc.result.outcome = "cancelled";
      else {
        acc.result.outcome = "abnormal";
        acc.result.errorMessage = "The response body could not be read completely.";
      }
      return acc.result;
    }
  }

  if (!res.body) {
    acc.result.outcome = "abnormal";
    acc.result.errorMessage = "The gateway response had no readable stream.";
    return acc.result;
  }

  const parser = new SseParser();
  const reader = res.body.getReader();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      let changed = false;
      for (const ev of parser.feed(value)) changed = acc.frame(ev.data) || changed;
      if (changed) emit();
      if (acc.result.outcome === "provider_error") {
        void reader.cancel().catch(() => undefined);
        emit();
        return acc.result;
      }
    }
    const tail = parser.end();
    for (const ev of tail.events) acc.frame(ev.data);
  } catch {
    if (opts.signal?.aborted) {
      acc.result.outcome = "cancelled";
    } else {
      acc.result.outcome = "abnormal";
      acc.result.errorMessage = "The connection dropped mid-stream. The response is incomplete and was not retried.";
    }
    emit();
    return acc.result;
  }
  const final = acc.finalize();
  emit();
  return final;
}