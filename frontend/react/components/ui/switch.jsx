import * as React from "react"
import { cn } from "cn"
import { Switch as SwitchPrimitive } from "radix-ui"

function Switch({
  className,
  size = "default",
  ...props
}) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      data-size={size}
      className={cn(
        "atl:peer atl:group/switch atl:inline-flex atl:shrink-0 atl:items-center atl:rounded-full atl:border atl:border-transparent atl:shadow-xs atl:transition-all atl:outline-none atl:focus-visible:border-ring atl:focus-visible:ring-[3px] atl:focus-visible:ring-ring/50 atl:disabled:cursor-not-allowed atl:disabled:opacity-50 atl:data-[size=default]:h-[1.15rem] atl:data-[size=default]:w-8 atl:data-[size=sm]:h-3.5 atl:data-[size=sm]:w-6 atl:data-[state=checked]:bg-primary atl:data-[state=unchecked]:bg-input atl:dark:data-[state=unchecked]:bg-input/80",
        className
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className={cn(
          "atl:pointer-events-none atl:block atl:rounded-full atl:bg-background atl:ring-0 atl:transition-transform atl:group-data-[size=default]/switch:size-4 atl:group-data-[size=sm]/switch:size-3 atl:data-[state=checked]:translate-x-[calc(100%-2px)] atl:data-[state=unchecked]:translate-x-0 atl:dark:data-[state=checked]:bg-primary-foreground atl:dark:data-[state=unchecked]:bg-foreground"
        )}
      />
    </SwitchPrimitive.Root>
  )
}

export { Switch }
