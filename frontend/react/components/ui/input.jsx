import * as React from "react"
import { cn } from "cn"

function Input({
  className,
  type,
  ...props
}) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "atl:h-9 atl:w-full atl:min-w-0 atl:rounded-md atl:border atl:border-input atl:bg-transparent atl:px-3 atl:py-1 atl:text-base atl:shadow-xs atl:transition-[color,box-shadow] atl:outline-none atl:selection:bg-primary atl:selection:text-primary-foreground atl:file:inline-flex atl:file:h-7 atl:file:border-0 atl:file:bg-transparent atl:file:text-sm atl:file:font-medium atl:file:text-foreground atl:placeholder:text-muted-foreground atl:disabled:pointer-events-none atl:disabled:cursor-not-allowed atl:disabled:opacity-50 atl:md:text-sm atl:dark:bg-input/30",
        "atl:focus-visible:border-ring atl:focus-visible:ring-[3px] atl:focus-visible:ring-ring/50",
        "atl:aria-invalid:border-destructive atl:aria-invalid:ring-destructive/20 atl:dark:aria-invalid:ring-destructive/40",
        className
      )}
      {...props}
    />
  )
}

export { Input }
