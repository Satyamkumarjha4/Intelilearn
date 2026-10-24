import { cva, type VariantProps } from "class-variance-authority"
import * as React from "react"
import { cn } from "cn"

const badgeVariants = cva(
  "inline-flex w-fit shrink-0 items-center gap-1 rounded-full border border-transparent px-2 py-0.5 text-xs font-medium whitespace-nowrap",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground",
        secondary: "bg-secondary text-secondary-foreground",
        outline: "border-border text-foreground",
        destructive: "bg-destructive/10 text-destructive dark:bg-destructive/20",
        success: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
      },
    },
    defaultVariants: { variant: "default" },
  }
)

function Badge({ className, variant, ...props }: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge, badgeVariants }
