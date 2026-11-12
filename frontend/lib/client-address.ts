/**
 * The visitor's address, from an `X-Forwarded-For` header, for the `/api` proxy to hand to Django.
 *
 * Next fills the header from the socket only when the client sent none, so a client's own value is kept. The entry to trust
 * is the one a proxy of ours appended: the last, or the Nth from the right when N trusted proxies sit in front of Next
 * (`EDGE_PROXY_HOPS`). Taking the first entry, as the proxy once did, let the client pick the address every limit counts.
 */
export class ClientAddress {
  /** `hops` trusted proxies in front: the entry `hops` places from the right, or the first when there are fewer. */
  static of(header: string | null | undefined, hops = 1): string | null {
    const entries = (header ?? "").split(",").map((entry) => entry.trim()).filter(Boolean);
    if (entries.length === 0) return null;
    return entries[Math.max(entries.length - hops, 0)] ?? null;
  }

  /** The number of trusted proxies in front of Next, from the environment text; anything but a whole number from 1 is one. */
  static hops(text: string | undefined): number {
    const value = Number(text?.trim());
    return Number.isInteger(value) && value >= 1 ? value : 1;
  }
}
