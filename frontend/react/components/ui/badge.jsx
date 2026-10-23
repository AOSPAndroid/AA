import * as React from "react"
import { cva } from "class-variance-authority";
import { cn } from "cn"
import { Slot } from "radix-ui"

const badgeVariants = cva(
  "atl:inline-flex atl:w-fit atl:shrink-0 atl:items-center atl:justify-center atl:gap-1 atl:overflow-hidden atl:rounded-full atl:border atl:border-transparent atl:px-2 atl:py-0.5 atl:text-xs atl:font-medium atl:whitespace-nowrap atl:transition-[color,box-shadow] atl:focus-visible:border-ring atl:focus-visible:ring-[3px] atl:focus-visible:ring-ring/50 atl:aria-invalid:border-destructive atl:aria-invalid:ring-destructive/20 atl:dark:aria-invalid:ring-destructive/40 atl:[&>svg]:pointer-events-none atl:[&>svg]:size-3",
  {
    variants: {
      variant: {
        default: "atl:bg-primary atl:text-primary-foreground atl:[a&]:hover:bg-primary/90",
        secondary:
          "atl:bg-secondary atl:text-secondary-foreground atl:[a&]:hover:bg-secondary/90",
        destructive:
          "atl:bg-destructive atl:text-white atl:focus-visible:ring-destructive/20 atl:dark:bg-destructive/60 atl:dark:focus-visible:ring-destructive/40 atl:[a&]:hover:bg-destructive/90",
        outline:
          "atl:border-border atl:text-foreground atl:[a&]:hover:bg-accent atl:[a&]:hover:text-accent-foreground",
        ghost: "atl:[a&]:hover:bg-accent atl:[a&]:hover:text-accent-foreground",
        link: "atl:text-primary atl:underline-offset-4 atl:[a&]:hover:underline",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant = "default",
  asChild = false,
  ...props
}) {
  const Comp = asChild ? Slot.Root : "span"

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  )
}

export { Badge, badgeVariants }
