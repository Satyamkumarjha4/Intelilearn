import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"

// The solid variants are "pressable": a flat shadow under the button that shrinks as it is pushed down. The press
// effect is a transform and a shadow change only, so it is switched off with the transition for reduced motion.
const PRESS = "active:translate-y-[3px] disabled:translate-y-0 disabled:bg-muted disabled:text-muted-foreground disabled:opacity-100"

const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center rounded-xl border border-transparent bg-clip-padding text-sm font-extrabold whitespace-nowrap outline-none select-none motion-safe:transition-[transform,box-shadow,background-color,color] focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: `bg-primary text-primary-foreground shadow-[0_4px_0_var(--primary-deep)] hover:bg-primary/90 active:shadow-[0_1px_0_var(--primary-deep)] disabled:shadow-[0_4px_0_var(--border)] ${PRESS}`,
        marigold: `bg-marigold text-marigold-foreground shadow-[0_4px_0_var(--marigold-deep)] hover:bg-marigold/90 active:shadow-[0_1px_0_var(--marigold-deep)] disabled:shadow-[0_4px_0_var(--border)] ${PRESS}`,
        outline: `border-2 border-border bg-card text-foreground shadow-[0_3px_0_var(--border)] hover:bg-muted active:shadow-[0_1px_0_var(--border)] aria-expanded:bg-muted disabled:border-border disabled:shadow-[0_3px_0_var(--border)] ${PRESS}`,
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-[color-mix(in_oklch,var(--secondary),var(--foreground)_5%)] aria-expanded:bg-secondary aria-expanded:text-secondary-foreground disabled:opacity-50",
        ghost:
          "hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground disabled:opacity-50 dark:hover:bg-muted/50",
        destructive:
          "bg-destructive-soft text-destructive-text hover:bg-destructive/20 focus-visible:border-destructive/40 focus-visible:ring-destructive/20 disabled:opacity-50 dark:focus-visible:ring-destructive/40",
        link: "text-primary-text underline-offset-4 hover:underline disabled:opacity-50",
      },
      size: {
        default:
          "h-8 gap-1.5 px-2.5 has-data-[icon=inline-end]:pr-2 has-data-[icon=inline-start]:pl-2",
        xs: "h-6 gap-1 rounded-[min(var(--radius-md),10px)] px-2 text-xs in-data-[slot=button-group]:rounded-lg has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3",
        sm: "h-7 gap-1 rounded-[min(var(--radius-md),12px)] px-2.5 text-[0.8rem] in-data-[slot=button-group]:rounded-lg has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-9 gap-1.5 px-2.5 has-data-[icon=inline-end]:pr-2 has-data-[icon=inline-start]:pl-2",
        xl: "h-12 gap-2 rounded-2xl px-6 text-[17px]",
        icon: "size-8",
        "icon-xs":
          "size-6 rounded-[min(var(--radius-md),10px)] in-data-[slot=button-group]:rounded-lg [&_svg:not([class*='size-'])]:size-3",
        "icon-sm":
          "size-7 rounded-[min(var(--radius-md),12px)] in-data-[slot=button-group]:rounded-lg",
        "icon-lg": "size-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants>) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
