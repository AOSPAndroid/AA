import * as React from "react"
import { cva } from "class-variance-authority";
import { cn } from "cn"

const alertVariants = cva(
  "atl:relative atl:grid atl:w-full atl:grid-cols-[0_1fr] atl:items-start atl:gap-y-0.5 atl:rounded-lg atl:border atl:px-4 atl:py-3 atl:text-sm atl:has-[>svg]:grid-cols-[calc(var(--spacing)*4)_1fr] atl:has-[>svg]:gap-x-3 atl:[&>svg]:size-4 atl:[&>svg]:translate-y-0.5 atl:[&>svg]:text-current",
  {
    variants: {
      variant: {
        default: "atl:bg-card atl:text-card-foreground",
        destructive:
          "atl:bg-card atl:text-destructive atl:*:data-[slot=alert-description]:text-destructive/90 atl:[&>svg]:text-current",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Alert({
  className,
  variant,
  ...props
}) {
  return (
    <div
      data-slot="alert"
      role="alert"
      className={cn(alertVariants({ variant }), className)}
      {...props}
    />
  )
}

function AlertTitle({
  className,
  ...props
}) {
  return (
    <div
      data-slot="alert-title"
      className={cn(
        "atl:col-start-2 atl:line-clamp-1 atl:min-h-4 atl:font-medium atl:tracking-tight",
        className
      )}
      {...props}
    />
  )
}

function AlertDescription({
  className,
  ...props
}) {
  return (
    <div
      data-slot="alert-description"
      className={cn(
        "atl:col-start-2 atl:grid atl:justify-items-start atl:gap-1 atl:text-sm atl:text-muted-foreground atl:[&_p]:leading-relaxed",
        className
      )}
      {...props}
    />
  )
}

export { Alert, AlertTitle, AlertDescription }
