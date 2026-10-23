"use client"

import * as React from "react"
import { cn } from "cn"
import { Label as LabelPrimitive } from "radix-ui"

function Label({
  className,
  ...props
}) {
  return (
    <LabelPrimitive.Root
      data-slot="label"
      className={cn(
        "atl:flex atl:items-center atl:gap-2 atl:text-sm atl:leading-none atl:font-medium atl:select-none atl:group-data-[disabled=true]:pointer-events-none atl:group-data-[disabled=true]:opacity-50 atl:peer-disabled:cursor-not-allowed atl:peer-disabled:opacity-50",
        className
      )}
      {...props}
    />
  )
}

export { Label }
