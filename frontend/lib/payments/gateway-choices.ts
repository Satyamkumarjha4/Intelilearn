import type { GatewayChoice, Gateways } from "./types";

/** Which way to pay, and whether to ask. The picker appears only when there is something to choose between (D13). */
export class GatewayChoices {
  static open(gateways: Gateways): boolean {
    return gateways.gateways.length > 0;
  }

  static showPicker(gateways: Gateways): boolean {
    return gateways.gateways.length >= 2;
  }

  /** The one selected at first: the default when it is on, else the first. */
  static initial(gateways: Gateways): string | null {
    const keys = gateways.gateways.map((g) => g.key);
    if (gateways.default && keys.includes(gateways.default)) return gateways.default;
    return keys[0] ?? null;
  }

  /** What to send as `gateway`: nothing when there is no choice to make, so the server uses its default. */
  static request(gateways: Gateways, picked: string | null): string | undefined {
    return GatewayChoices.showPicker(gateways) && picked ? picked : undefined;
  }

  static label(gateways: Gateways, key: string): GatewayChoice | undefined {
    return gateways.gateways.find((g) => g.key === key);
  }
}
