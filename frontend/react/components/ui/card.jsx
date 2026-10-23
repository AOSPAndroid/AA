import * as React from "react"
import { cn } from "cn"

function Card({
  className,
  ...props
}) {
  return (
    <div
      data-slot="card"
      className={cn(
        "atl:flex atl:flex-col atl:gap-6 atl:rounded-xl atl:border atl:bg-card atl:py-6 atl:text-card-foreground atl:shadow-sm",
        className
      )}
      {...props}
    />
  )
}

function CardHeader({
  className,
  ...props
}) {
  return (
    <div
      data-slot="card-header"
      className={cn(
        "atl:@container/card-header atl:grid atl:auto-rows-min atl:grid-rows-[auto_auto] atl:items-start atl:gap-2 atl:px-6 atl:has-data-[slot=card-action]:grid-cols-[1fr_auto] atl:[.border-b]:pb-6",
        className
      )}
      {...props}
    />
  )
}

function CardTitle({
  className,
  ...props
}) {
  return (
    <div
      data-slot="card-title"
      className={cn("atl:leading-none atl:font-semibold", className)}
      {...props}
    />
  )
}

function CardDescription({
  className,
  ...props
}) {
  return (
    <div
      data-slot="card-description"
      className={cn("atl:text-sm atl:text-muted-foreground", className)}
      {...props}
    />
  )
}

function CardAction({
  className,
  ...props
}) {
  return (
    <div
      data-slot="card-action"
      className={cn(
        "atl:col-start-2 atl:row-span-2 atl:row-start-1 atl:self-start atl:justify-self-end",
        className
      )}
      {...props}
    />
  )
}

function CardContent({
  className,
  ...props
}) {
  return (
    <div
      data-slot="card-content"
      className={cn("atl:px-6", className)}
      {...props}
    />
  )
}

function CardFooter({
  className,
  ...props
}) {
  return (
    <div
      data-slot="card-footer"
      className={cn("atl:flex atl:items-center atl:px-6 atl:[.border-t]:pt-6", className)}
      {...props}
    />
  )
}

export {
  Card,
  CardHeader,
  CardFooter,
  CardTitle,
  CardAction,
  CardDescription,
  CardContent,
}
