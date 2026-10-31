// Minimal parser/matcher for the Cloudflare Pages `_headers` format, used by the local
// preview server and the tests. Supports exact paths and a single trailing splat.

export function parseHeaders(text) {
  const rules = [];
  let current = null;
  for (const rawLine of text.split(/\r?\n/u)) {
    if (rawLine.trim() === "" || rawLine.trimStart().startsWith("#")) continue;
    if (!/^\s/u.test(rawLine)) {
      current = { pattern: rawLine.trim(), set: [], detach: [] };
      rules.push(current);
      continue;
    }
    if (!current) throw new Error(`Header line without a path: ${rawLine}`);
    const line = rawLine.trim();
    if (line.startsWith("! ")) {
      current.detach.push(line.slice(2).trim().toLowerCase());
      continue;
    }
    const separator = line.indexOf(":");
    if (separator <= 0) throw new Error(`Invalid header line: ${rawLine}`);
    current.set.push([line.slice(0, separator).trim(), line.slice(separator + 1).trim()]);
  }
  return rules;
}

export function matches(pattern, pathname) {
  if (pattern.endsWith("*")) return pathname.startsWith(pattern.slice(0, -1));
  return pattern === pathname;
}

export function headersFor(rules, pathname) {
  const result = new Map();
  for (const rule of rules) {
    if (!matches(rule.pattern, pathname)) continue;
    for (const name of rule.detach) result.delete(name);
    for (const [name, value] of rule.set) {
      const key = name.toLowerCase();
      const previous = result.get(key);
      result.set(key, previous ? { name, value: `${previous.value}, ${value}` } : { name, value });
    }
  }
  return Object.fromEntries([...result.values()].map(({ name, value }) => [name, value]));
}

export function parseCsp(value) {
  const directives = new Map();
  for (const part of value.split(";")) {
    const [name, ...sources] = part.trim().split(/\s+/u);
    if (name) directives.set(name.toLowerCase(), sources);
  }
  return directives;
}
