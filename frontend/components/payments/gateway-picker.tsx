"use client";

import { ChoiceCards } from "@/components/lessons/choice-cards";
import { GatewayChoices } from "@/lib/payments/gateway-choices";
import type { Gateways } from "@/lib/payments/types";

/** How to pay, asked only when there is more than one way (credits plan D13). */
export function GatewayPicker({ gateways, value, onChange, disabled }: { gateways: Gateways; value: string; onChange: (key: string) => void; disabled?: boolean }) {
  if (!GatewayChoices.showPicker(gateways)) return null;
  return (
    <ChoiceCards
      name="gateway"
      legend="How would you like to pay?"
      choices={gateways.gateways.map((g) => ({ id: g.key, label: g.display_name, hint: "" }))}
      value={value}
      onChange={onChange}
      disabled={disabled}
    />
  );
}
