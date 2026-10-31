/**
 * Rate-limit subject for a client address. IPv4 clients are limited per address; IPv6 clients per
 * /64 prefix, because a single subscriber usually controls a whole /64 and could otherwise rotate
 * through 2^64 addresses. IPv4-mapped IPv6 addresses count as their IPv4 address. Anything that is
 * not a valid address shares the `unknown` bucket.
 */
export function rateLimitSubject(address: string | null): string {
  const value = address?.trim() ?? "";
  const ipv4 = parseIpv4(value);
  if (ipv4 !== null) return `v4:${ipv4.join(".")}`;
  const ipv6 = parseIpv6(value);
  if (ipv6 === null) return "unknown";
  if (ipv6.slice(0, 5).every((group) => group === 0) && ipv6[5] === 0xffff) {
    const high = ipv6[6] ?? 0;
    const low = ipv6[7] ?? 0;
    return `v4:${[high >> 8, high & 0xff, low >> 8, low & 0xff].join(".")}`;
  }
  return `v6:${ipv6.slice(0, 4).map((group) => group.toString(16).padStart(4, "0")).join(":")}::/64`;
}

function parseIpv4(value: string): number[] | null {
  const parts = value.split(".");
  if (parts.length !== 4) return null;
  const octets: number[] = [];
  for (const part of parts) {
    if (!/^(?:0|[1-9][0-9]{0,2})$/.test(part)) return null;
    const octet = Number(part);
    if (octet > 255) return null;
    octets.push(octet);
  }
  return octets;
}

/** The eight 16-bit groups of an IPv6 address, or `null`. */
function parseIpv6(value: string): number[] | null {
  if (value.length === 0 || value.length > 64 || !value.includes(":")) return null;
  const address = value.split("%", 1)[0] ?? "";
  const halves = address.split("::");
  if (halves.length > 2) return null;
  const parse = (part: string): number[] | null => {
    if (part === "") return [];
    const groups: number[] = [];
    const pieces = part.split(":");
    for (const [index, piece] of pieces.entries()) {
      if (index === pieces.length - 1 && piece.includes(".")) {
        const ipv4 = parseIpv4(piece);
        if (ipv4 === null) return null;
        groups.push(((ipv4[0] ?? 0) << 8) | (ipv4[1] ?? 0), ((ipv4[2] ?? 0) << 8) | (ipv4[3] ?? 0));
        continue;
      }
      if (!/^[0-9a-fA-F]{1,4}$/.test(piece)) return null;
      groups.push(parseInt(piece, 16));
    }
    return groups;
  };
  const head = parse(halves[0] ?? "");
  const tail = halves.length === 2 ? parse(halves[1] ?? "") : [];
  if (head === null || tail === null) return null;
  if (halves.length === 1) return head.length === 8 ? head : null;
  const missing = 8 - head.length - tail.length;
  if (missing < 1) return null;
  return [...head, ...new Array<number>(missing).fill(0), ...tail];
}
