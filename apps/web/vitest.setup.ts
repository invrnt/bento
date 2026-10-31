import "@testing-library/jest-dom/vitest";

// Tests assert the default Spanish copy, but jsdom reports `en-US`; pin it before the dictionary loads.
Object.defineProperty(globalThis.navigator, "language", { configurable: true, value: "es-ES" });

// Node 26 shadows jsdom's Web Storage with its own (undefined without --localstorage-file); install a memory store.
// Typed structurally: this file is also checked by tsconfig.node.json, which has no DOM lib.
const host = globalThis as { localStorage?: unknown };
if ("document" in globalThis && !host.localStorage) {
  const values = new Map<string, string>();
  const storage = {
    clear: () => values.clear(),
    getItem: (key: string) => values.get(key) ?? null,
    key: (index: number) => [...values.keys()][index] ?? null,
    get length() {
      return values.size;
    },
    removeItem: (key: string) => void values.delete(key),
    setItem: (key: string, value: string) => void values.set(key, String(value)),
  };
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: storage });
}
