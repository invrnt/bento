const SENSITIVE_KEY = /(?:authorization|cookie|password|secret|token|api[_-]?hash|chat[_-]?id|wrapping[_-]?key|recovery[_-]?code|session)/iu;
const BEARER = /\bBearer\s+[A-Za-z0-9._~+/=-]+/giu;
const QUERY_SECRET = /([?&](?:token|password|secret|api[_-]?hash)=)[^&\s]+/giu;

export function redact<T>(value: T, secretValues: readonly string[] = []): T {
  const cleanString = (input: string): string => {
    let output = input.replace(BEARER, "Bearer [REDACTED]").replace(QUERY_SECRET, "$1[REDACTED]");
    for (const secret of secretValues) {
      if (secret.length >= 4) output = output.split(secret).join("[REDACTED]");
    }
    return output;
  };
  const visit = (input: unknown, seen: WeakSet<object>): unknown => {
    if (typeof input === "string") return cleanString(input);
    if (input === null || typeof input !== "object") return input;
    if (seen.has(input)) return "[CIRCULAR]";
    seen.add(input);
    if (Array.isArray(input)) return input.map((item) => visit(item, seen));
    return Object.fromEntries(Object.entries(input as Record<string, unknown>).map(([key, item]) => [
      key,
      SENSITIVE_KEY.test(key) ? "[REDACTED]" : visit(item, seen),
    ]));
  };
  return visit(value, new WeakSet()) as T;
}

export class RedactingLog {
  constructor(
    private readonly writeLine: (line: string) => void,
    private readonly secrets: () => readonly string[] = () => [],
  ) {}

  write(level: "info" | "warn" | "error", message: string, context: unknown = {}): void {
    const entry = redact({ timestamp: new Date().toISOString(), level, message, context }, this.secrets());
    this.writeLine(JSON.stringify(entry));
  }
}
