import { describe, expect, it } from "vitest";
import { chatCompletion } from "./chat";

const enc = new TextEncoder();
const frame = (o: unknown) => `data: ${typeof o === "string" ? o : JSON.stringify(o)}\n\n`;
const chunk = (delta: object, finish: string | null = null) => ({ choices: [{ index: 0, delta, finish_reason: finish }] });

function streamResponse(parts: string[], opts: { error?: boolean } = {}): Response {
  let i = 0;
  const body = new ReadableStream<Uint8Array>({
    pull(c) {
      if (i < parts.length) c.enqueue(enc.encode(parts[i++]!));
      else if (opts.error) c.error(new Error("reset"));
      else c.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

const base = { gatewayUrl: "https://gw.test/v1", key: "sk-test", stream: true, request: { model: "m", messages: [{ role: "user" as const, content: "hi" }] } };

describe("chatCompletion streaming", () => {
  it("sends the documented request and completes normally with usage-only frame", async () => {
    let seen: { url: string; init: RequestInit } | undefined;
    const fetchImpl = (async (url: string, init: RequestInit) => {
      seen = { url, init };
      return streamResponse([
        frame(chunk({ role: "assistant", content: "Hel" })),
        frame(chunk({ content: "lo" }, "stop")),
        frame({ choices: [], usage: { prompt_tokens: 3, completion_tokens: 2, total_tokens: 5 } }),
        frame("[DONE]"),
      ]);
    }) as unknown as typeof fetch;
    const r = await chatCompletion({ ...base, fetchImpl });
    expect(r.outcome).toBe("completed");
    expect(r.content).toBe("Hello");
    expect(r.usage?.total_tokens).toBe(5);
    expect(seen!.url).toBe("https://gw.test/v1/chat/completions");
    const headers = seen!.init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer sk-test");
    expect(seen!.init.cache).toBe("no-store");
    const body = JSON.parse(seen!.init.body as string);
    expect(body.stream).toBe(true);
    expect(body.stream_options).toEqual({ include_usage: true });
  });

  it("assembles fragmented tool-call deltas and never executes them", async () => {
    const fetchImpl = (async () =>
      streamResponse([
        frame(chunk({ tool_calls: [{ index: 0, id: "call_1", function: { name: "get_", arguments: "" } }] })),
        frame(chunk({ tool_calls: [{ index: 0, function: { name: "weather", arguments: '{"ci' } }] })),
        frame(chunk({ tool_calls: [{ index: 0, function: { arguments: 'ty":"SG"}' } }] }, "tool_calls")),
        frame("[DONE]"),
      ])) as unknown as typeof fetch;
    const r = await chatCompletion({ ...base, fetchImpl });
    expect(r.outcome).toBe("completed");
    expect(r.toolCalls).toEqual([{ index: 0, id: "call_1", name: "get_weather", arguments: '{"city":"SG"}' }]);
  });

  it("flags a stream truncated before [DONE] as abnormal", async () => {
    const fetchImpl = (async () => streamResponse([frame(chunk({ content: "partial" }))])) as unknown as typeof fetch;
    const r = await chatCompletion({ ...base, fetchImpl });
    expect(r.outcome).toBe("abnormal");
    expect(r.content).toBe("partial");
    expect(r.errorMessage).toMatch(/\[DONE\]/);
  });

  it("flags a mid-stream connection error as abnormal without retrying", async () => {
    let calls = 0;
    const fetchImpl = (async () => { calls++; return streamResponse([frame(chunk({ content: "x" }))], { error: true }); }) as unknown as typeof fetch;
    const r = await chatCompletion({ ...base, fetchImpl });
    expect(r.outcome).toBe("abnormal");
    expect(calls).toBe(1);
  });

  it("only reports content_filter when the server sent it", async () => {
    const fetchImpl = (async () => streamResponse([frame(chunk({ content: "a" }, "content_filter")), frame("[DONE]")])) as unknown as typeof fetch;
    expect((await chatCompletion({ ...base, fetchImpl })).outcome).toBe("content_filter");
  });

  it("distinguishes length, provider error frame and HTTP errors", async () => {
    const len = (async () => streamResponse([frame(chunk({ content: "a" }, "length")), frame("[DONE]")])) as unknown as typeof fetch;
    expect((await chatCompletion({ ...base, fetchImpl: len })).outcome).toBe("length");
    const err = (async () => streamResponse([frame({ error: { message: "upstream boom" } })])) as unknown as typeof fetch;
    const r = await chatCompletion({ ...base, fetchImpl: err });
    expect(r.outcome).toBe("provider_error");
    expect(r.errorMessage).toBe("upstream boom");
    const http = (async () => new Response(JSON.stringify({ error: { message: "slow down" } }), { status: 429, headers: { "Retry-After": "7" } })) as unknown as typeof fetch;
    const h = await chatCompletion({ ...base, fetchImpl: http });
    expect(h).toMatchObject({ outcome: "http_error", httpStatus: 429, retryAfter: "7", errorMessage: "slow down" });
  });

  it("reports user cancellation distinctly", async () => {
    const ctrl = new AbortController();
    const fetchImpl = ((_u: string, init: RequestInit) =>
      new Promise((_res, rej) => {
        init.signal!.addEventListener("abort", () => rej(new DOMException("aborted", "AbortError")));
      })) as unknown as typeof fetch;
    const p = chatCompletion({ ...base, signal: ctrl.signal, fetchImpl });
    ctrl.abort();
    expect((await p).outcome).toBe("cancelled");
  });

  it("supports non-streaming responses without stream_options", async () => {
    let body: Record<string, unknown> = {};
    const fetchImpl = (async (_u: string, init: RequestInit) => {
      body = JSON.parse(init.body as string);
      return new Response(JSON.stringify({ choices: [{ message: { content: "ok" }, finish_reason: "stop" }], usage: { total_tokens: 2 } }), { status: 200 });
    }) as unknown as typeof fetch;
    const r = await chatCompletion({ ...base, stream: false, fetchImpl });
    expect(r).toMatchObject({ outcome: "completed", content: "ok" });
    expect(body.stream).toBe(false);
    expect(body.stream_options).toBeUndefined();
  });
});