import { describe, expect, it } from "vitest";
import { SseParser } from "./sse";

const enc = new TextEncoder();

describe("SseParser", () => {
  it("parses CRLF events and multi-line data", () => {
    const p = new SseParser();
    const evs = p.feed(enc.encode("data: a\r\ndata: b\r\n\r\ndata: c\r\n\r\n"));
    expect(evs.map((e) => e.data)).toEqual(["a\nb", "c"]);
  });

  it("handles CRLF split across chunks and lone CR", () => {
    const p = new SseParser();
    const out = [...p.feed(enc.encode("data: x\r")), ...p.feed(enc.encode("\n\r")), ...p.feed(enc.encode("\ndata: y\r\rdata: z\n\n"))];
    expect(out.map((e) => e.data)).toEqual(["x", "y", "z"]);
  });

  it("reassembles multi-byte UTF-8 split across every byte", () => {
    const bytes = enc.encode('data: {"t":"héllo 世界 😀"}\n\n');
    const p = new SseParser();
    const out = [];
    for (const b of bytes) out.push(...p.feed(new Uint8Array([b])));
    expect(out).toHaveLength(1);
    expect(JSON.parse(out[0]!.data).t).toBe("héllo 世界 😀");
  });

  it("ignores comments, strips BOM, reports partial trailing event", () => {
    const p = new SseParser();
    const out = p.feed(enc.encode("\ufeff: ping\n\ndata: ok\n\ndata: cut"));
    expect(out.map((e) => e.data)).toEqual(["ok"]);
    const end = p.end();
    expect(end.events).toEqual([]);
    expect(end.partial).toBe(true);
  });

  it("does not report partial after clean end", () => {
    const p = new SseParser();
    p.feed(enc.encode("data: [DONE]\n\n"));
    expect(p.end().partial).toBe(false);
  });
});