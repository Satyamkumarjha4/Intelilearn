"use client"

import * as React from "react"
import { Switch as SwitchPrimitive } from "@base-ui/react/switch"
import { cn } from "cn"

function Switch({ className, ...props }: SwitchPrimitive.Root.Props) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn(
        "relative inline-flex h-6 w-10 shrink-0 items-center rounded-full bg-border outline-none motion-safe:transition-colors focus-visible:ring-3 focus-visible:ring-ring/50 data-checked:bg-primary data-disabled:cursor-not-allowed data-disabled:opacity-50",
        className
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className="block size-[18px] translate-x-[3px] rounded-full bg-card shadow-sm motion-safe:transition-transform data-checked:translate-x-[19px]"
      />
    </SwitchPrimitive.Root>
  )
}

export { Switch }
