import * as React from "react"
import { cva } from "class-variance-authority";
import { cn } from "cn"
import { Slot } from "radix-ui"

const buttonVariants = cva(
  "atl:inline-flex atl:shrink-0 atl:items-center atl:justify-center atl:gap-2 atl:rounded-md atl:text-sm atl:font-medium atl:whitespace-nowrap atl:transition-all atl:outline-none atl:focus-visible:border-ring atl:focus-visible:ring-[3px] atl:focus-visible:ring-ring/50 atl:disabled:pointer-events-none atl:disabled:opacity-50 atl:aria-invalid:border-destructive atl:aria-invalid:ring-destructive/20 atl:dark:aria-invalid:ring-destructive/40 atl:[&_svg]:pointer-events-none atl:[&_svg]:shrink-0 atl:[&_svg:not([class*=size-])]:size-4",
  {
    variants: {
      variant: {
        default: "atl:bg-primary atl:text-primary-foreground atl:hover:bg-primary/90",
        destructive:
          "atl:bg-destructive atl:text-white atl:hover:bg-destructive/90 atl:focus-visible:ring-destructive/20 atl:dark:bg-destructive/60 atl:dark:focus-visible:ring-destructive/40",
        outline:
          "atl:border atl:bg-background atl:shadow-xs atl:hover:bg-accent atl:hover:text-accent-foreground atl:dark:border-input atl:dark:bg-input/30 atl:dark:hover:bg-input/50",
        secondary:
          "atl:bg-secondary atl:text-secondary-foreground atl:hover:bg-secondary/80",
        ghost:
          "atl:hover:bg-accent atl:hover:text-accent-foreground atl:dark:hover:bg-accent/50",
        link: "atl:text-primary atl:underline-offset-4 atl:hover:underline",
      },
      size: {
        default: "atl:h-9 atl:px-4 atl:py-2 atl:has-[>svg]:px-3",
        xs: "atl:h-6 atl:gap-1 atl:rounded-md atl:px-2 atl:text-xs atl:has-[>svg]:px-1.5 atl:[&_svg:not([class*=size-])]:size-3",
        sm: "atl:h-8 atl:gap-1.5 atl:rounded-md atl:px-3 atl:has-[>svg]:px-2.5",
        lg: "atl:h-10 atl:rounded-md atl:px-6 atl:has-[>svg]:px-4",
        icon: "atl:size-9",
        "icon-xs": "atl:size-6 atl:rounded-md atl:[&_svg:not([class*=size-])]:size-3",
        "icon-sm": "atl:size-8",
        "icon-lg": "atl:size-10",
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
  asChild = false,
  ...props
}) {
  const Comp = asChild ? Slot.Root : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
