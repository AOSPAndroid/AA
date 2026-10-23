import * as React from "react"
import { cva } from "class-variance-authority";
import { cn } from "cn"

function Empty({
  className,
  ...props
}) {
  return (
    <div
      data-slot="empty"
      className={cn(
        "atl:flex atl:min-w-0 atl:flex-1 atl:flex-col atl:items-center atl:justify-center atl:gap-6 atl:rounded-lg atl:border atl:border-dashed atl:border-border atl:p-6 atl:text-center atl:text-balance atl:md:p-12",
        className
      )}
      {...props}
    />
  )
}

function EmptyHeader({
  className,
  ...props
}) {
  return (
    <div
      data-slot="empty-header"
      className={cn(
        "atl:flex atl:max-w-sm atl:flex-col atl:items-center atl:gap-2 atl:text-center",
        className
      )}
      {...props}
    />
  )
}

const emptyMediaVariants = cva(
  "atl:mb-2 atl:flex atl:shrink-0 atl:items-center atl:justify-center atl:[&_svg]:pointer-events-none atl:[&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "atl:bg-transparent",
        icon: "atl:flex atl:size-10 atl:shrink-0 atl:items-center atl:justify-center atl:rounded-lg atl:bg-muted atl:text-foreground atl:[&_svg:not([class*=size-])]:size-6",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function EmptyMedia({
  className,
  variant = "default",
  ...props
}) {
  return (
    <div
      data-slot="empty-icon"
      data-variant={variant}
      className={cn(emptyMediaVariants({ variant, className }))}
      {...props}
    />
  )
}

function EmptyTitle({
  className,
  ...props
}) {
  return (
    <div
      data-slot="empty-title"
      className={cn("atl:text-lg atl:font-medium atl:tracking-tight", className)}
      {...props}
    />
  )
}

function EmptyDescription({
  className,
  ...props
}) {
  return (
    <div
      data-slot="empty-description"
      className={cn(
        "atl:text-sm/relaxed atl:text-muted-foreground atl:[&>a]:underline atl:[&>a]:underline-offset-4 atl:[&>a:hover]:text-primary",
        className
      )}
      {...props}
    />
  )
}

function EmptyContent({
  className,
  ...props
}) {
  return (
    <div
      data-slot="empty-content"
      className={cn(
        "atl:flex atl:w-full atl:max-w-sm atl:min-w-0 atl:flex-col atl:items-center atl:gap-4 atl:text-sm atl:text-balance",
        className
      )}
      {...props}
    />
  )
}

export {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
  EmptyContent,
  EmptyMedia,
}
