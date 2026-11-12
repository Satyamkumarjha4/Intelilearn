/**
 * Unit under test: `ClientAddress`, which picks the visitor's address out of an `X-Forwarded-For` header for the `/api` proxy.
 *
 * Why: every per-address limit of the API (sign-up, code sends, login) counts by the address the proxy forwards. Next
 * fills the header from the socket only when the client sent none, so a client that sends its own chooses its own
 * address, and an edge proxy that *appends* the address it saw leaves the client's value first. The proxy used to take
 * the first entry, so anyone could pick a new address for every request and never be limited. The entry that counts is
 * the one the trusted proxy nearest to us appended: the last, or the Nth from the right when N proxies sit in front.
 * Measured on the real stack (a forged first entry beside a fixed last one was never limited, a fixed last one was).
 * With nothing in front, a client that sends one forged entry still picks its own address: only an edge that
 * overwrites or appends closes that, and the deployment notes say so.
 *
 * Use cases:
 * - one entry is the address (the usual case: Next filled it from the socket, or an edge overwrote it)
 * - several entries: the last is the address, whatever the client put before it
 * - with N trusted hops in front, the Nth entry from the right is the address
 * - more hops than entries falls back to the first entry (there is nothing better to trust)
 * - blanks, spaces and empty entries are ignored; no header, or only blanks, is no address
 * - the number of hops is read from the environment text, and a bad value means one
 */
import { describe, expect, test } from "bun:test";

import { ClientAddress } from "./client-address";

describe("ClientAddress", () => {
  test("one entry is the address", () => {
    expect(ClientAddress.of("203.0.113.7")).toBe("203.0.113.7");
  });

  test("with several entries the last one counts, whatever the client put before it", () => {
    expect(ClientAddress.of("198.51.100.1, 203.0.113.9")).toBe("203.0.113.9");
    expect(ClientAddress.of("198.51.100.1,198.51.100.2 , 203.0.113.9")).toBe("203.0.113.9");
  });

  test("with N trusted hops in front, the Nth entry from the right counts", () => {
    expect(ClientAddress.of("forged, 203.0.113.9, 10.0.0.2", 2)).toBe("203.0.113.9");
    expect(ClientAddress.of("forged, 203.0.113.9, 10.0.0.2", 1)).toBe("10.0.0.2");
  });

  test("more hops than entries falls back to the first entry", () => {
    expect(ClientAddress.of("203.0.113.9", 3)).toBe("203.0.113.9");
  });

  test("blanks and empty entries are ignored", () => {
    expect(ClientAddress.of(" 203.0.113.9 ,, ")).toBe("203.0.113.9");
    expect(ClientAddress.of("")).toBeNull();
    expect(ClientAddress.of(" , ")).toBeNull();
    expect(ClientAddress.of(null)).toBeNull();
  });

  test("the hops come from the environment text; a bad value is one", () => {
    expect(ClientAddress.hops("2")).toBe(2);
    expect(ClientAddress.hops(" 3 ")).toBe(3);
    expect(ClientAddress.hops(undefined)).toBe(1);
    expect(ClientAddress.hops("")).toBe(1);
    expect(ClientAddress.hops("0")).toBe(1);
    expect(ClientAddress.hops("-2")).toBe(1);
    expect(ClientAddress.hops("two")).toBe(1);
    expect(ClientAddress.hops("1.5")).toBe(1);
  });
});
