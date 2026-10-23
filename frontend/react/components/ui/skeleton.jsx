import * as React from "react"
import { cn } from "cn"

function Skeleton({
  className,
  ...props
}) {
  return (
    <div
      data-slot="skeleton"
      className={cn("atl:animate-pulse atl:rounded-md atl:bg-accent", className)}
      {...props}
    />
  )
}

export { Skeleton }
