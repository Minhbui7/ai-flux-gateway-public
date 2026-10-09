export interface SseEvent {
  event: string;
  data: string;
  id?: string;
}

/**
 * Incremental Server-Sent Events parser. Handles UTF-8 sequences split across
 * network chunks, CR / LF / CRLF line endings (including CRLF split across
 * chunks), multi-line data fields, comments and a leading BOM.
 */
export class SseParser {
  private decoder = new TextDecoder("utf-8");
  private buffer = "";
  private started = false;
  private dataLines: string[] = [];
  private eventName = "";
  private lastId: string | undefined;
  private hasFields = false;

  /** True when bytes were received that never completed an event. */
  get hasPartial(): boolean {
    return this.hasFields || this.buffer.length > 0;
  }

  feed(chunk: Uint8Array): SseEvent[] {
    return this.feedText(this.decoder.decode(chunk, { stream: true }));
  }

  feedText(text: string): SseEvent[] {
    if (!this.started && text.length > 0) {
      this.started = true;
      if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
    }
    this.buffer += text;
    const events: SseEvent[] = [];
    let i = 0;
    const buf = this.buffer;
    while (i < buf.length) {
      let end = -1;
      let next = -1;
      for (let j = i; j < buf.length; j++) {
        const c = buf[j];
        if (c === "\n") {
          end = j;
          next = j + 1;
          break;
        }
        if (c === "\r") {
          if (j + 1 >= buf.length) break; // wait: may be CRLF split across chunks
          end = j;
          next = buf[j + 1] === "\n" ? j + 2 : j + 1;
          break;
        }
      }
      if (end < 0) break;
      const ev = this.line(buf.slice(i, end));
      if (ev) events.push(ev);
      i = next;
    }
    this.buffer = buf.slice(i);
    return events;
  }

  /** Call at end of stream. Incomplete trailing events are discarded per the SSE spec. */
  end(): { events: SseEvent[]; partial: boolean } {
    const tail = this.decoder.decode();
    const events = tail ? this.feedText(tail) : [];
    if (this.buffer.endsWith("\r")) {
      const ev = this.line(this.buffer.slice(0, -1));
      this.buffer = "";
      if (ev) events.push(ev);
    }
    return { events, partial: this.hasPartial };
  }

  private line(line: string): SseEvent | null {
    if (line === "") {
      if (!this.hasFields) return null;
      const ev: SseEvent = { event: this.eventName || "message", data: this.dataLines.join("\n"), id: this.lastId };
      this.dataLines = [];
      this.eventName = "";
      this.hasFields = false;
      return ev;
    }
    if (line.startsWith(":")) return null;
    const idx = line.indexOf(":");
    const field = idx < 0 ? line : line.slice(0, idx);
    let value = idx < 0 ? "" : line.slice(idx + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "data") {
      this.dataLines.push(value);
      this.hasFields = true;
    } else if (field === "event") {
      this.eventName = value;
      this.hasFields = true;
    } else if (field === "id") {
      this.lastId = value;
    }
    return null;
  }
}