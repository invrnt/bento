export interface RendererTarget {
  send(channel: string, payload: unknown): void;
  isDestroyed(): boolean;
}

/**
 * One-way main → renderer event stream that buffers until the renderer subscribes,
 * so events from a cold start or a reload are delivered exactly once.
 */
export class RendererEventQueue<T> {
  private target: RendererTarget | null = null;
  private buffer: T[] = [];

  constructor(
    private readonly channel: string,
    private readonly maxBuffered = 16,
    private readonly sameEvent: (left: T, right: T) => boolean = (left, right) => JSON.stringify(left) === JSON.stringify(right),
  ) {}

  get pending(): readonly T[] {
    return this.buffer;
  }

  get subscribed(): boolean {
    return this.target !== null && !this.target.isDestroyed();
  }

  push(event: T): void {
    if (this.subscribed) {
      this.target!.send(this.channel, event);
      return;
    }
    if (this.buffer.some((item) => this.sameEvent(item, event))) return;
    this.buffer.push(event);
    if (this.buffer.length > this.maxBuffered) this.buffer.shift();
  }

  subscribe(target: RendererTarget): void {
    this.target = target;
    const pending = this.buffer;
    this.buffer = [];
    for (const event of pending) target.send(this.channel, event);
  }

  unsubscribe(target: RendererTarget): void {
    if (this.target === target) this.target = null;
  }

  /** Called when the renderer document is replaced or crashes. */
  reset(): void {
    this.target = null;
  }
}
