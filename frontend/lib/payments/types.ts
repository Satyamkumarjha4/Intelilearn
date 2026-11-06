/** The shapes of the payments endpoints (docs/reference/api.md, "Payments"). Money is paise. */

export type GatewayChoice = { key: string; display_name: string };
export type Gateways = { gateways: GatewayChoice[]; default: string | null };

/** How the browser pays: go to a page, or open the provider's own on-page checkout with these (non-secret) parameters. */
export type Checkout =
  | { kind: "redirect"; redirect_url: string }
  | { kind: "client"; adapter: string; client: Record<string, unknown> };

export type OrderStatus = "created" | "pending" | "paid" | "fulfilled" | "failed" | "expired";

export type Order = {
  id: string;
  status: OrderStatus;
  gateway: string;
  plan: { key: string; name: string };
  quantity: number;
  /** What the order gives: credits bought, or a plan's credits in all. */
  credits: number;
  amount_paise: number;
  currency: string;
  refunded_paise: number;
  created_at: string;
  fulfilled_at: string | null;
};

export type CreatedOrder = Order & { checkout: Checkout };

/** What a learner asks to buy. The server prices it; no amount is ever sent. */
export type BuyRequest = { plan: string; quantity?: number; credits?: number; gateway?: string };
