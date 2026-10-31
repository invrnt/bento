export const OVERLONG_LINE = "[line exceeded the length limit and was discarded]";

/**
 * Splits a text stream into lines so redaction always sees whole lines: a secret split across two
 * chunks would otherwise slip past it. Overlong lines are dropped whole rather than truncated, so no
 * partial secret can survive a cut.
 */
export class LineSplitter {
  private buffer = "";
  private discarding = false;

  constructor(private readonly onLine: (line: string) => void, private readonly maxLength = 16 * 1024) {}

  push(chunk: string): void {
    let rest = chunk;
    for (let index = rest.indexOf("\n"); index !== -1; index = rest.indexOf("\n")) {
      const tail = rest.slice(0, index);
      rest = rest.slice(index + 1);
      if (this.discarding) this.discarding = false;
      else this.emit(this.buffer + tail);
      this.buffer = "";
    }
    if (this.discarding) return;
    this.buffer += rest;
    if (this.buffer.length > this.maxLength) {
      this.buffer = "";
      this.discarding = true;
      this.onLine(OVERLONG_LINE);
    }
  }

  end(): void {
    if (!this.discarding) this.emit(this.buffer);
    this.buffer = "";
    this.discarding = false;
  }

  private emit(raw: string): void {
    const line = raw.endsWith("\r") ? raw.slice(0, -1) : raw;
    if (!line) return;
    this.onLine(line.length > this.maxLength ? OVERLONG_LINE : line);
  }
}
