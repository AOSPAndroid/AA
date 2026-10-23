"use client"

import { useMemo } from "react"
import { cva } from "class-variance-authority";
import { cn } from "cn"

import { Label } from "@/components/ui/label"
import { Separator } from "@/components/ui/separator"

function FieldSet({
  className,
  ...props
}) {
  return (
    <fieldset
      data-slot="field-set"
      className={cn(
        "atl:flex atl:flex-col atl:gap-6",
        "atl:has-[>[data-slot=checkbox-group]]:gap-3 atl:has-[>[data-slot=radio-group]]:gap-3",
        className
      )}
      {...props}
    />
  )
}

function FieldLegend({
  className,
  variant = "legend",
  ...props
}) {
  return (
    <legend
      data-slot="field-legend"
      data-variant={variant}
      className={cn(
        "atl:mb-3 atl:font-medium",
        "atl:data-[variant=legend]:text-base",
        "atl:data-[variant=label]:text-sm",
        className
      )}
      {...props}
    />
  )
}

function FieldGroup({
  className,
  ...props
}) {
  return (
    <div
      data-slot="field-group"
      className={cn(
        "atl:group/field-group atl:@container/field-group atl:flex atl:w-full atl:flex-col atl:gap-7 atl:data-[slot=checkbox-group]:gap-3 atl:[&>[data-slot=field-group]]:gap-4",
        className
      )}
      {...props}
    />
  )
}

const fieldVariants = cva(
  "atl:group/field atl:flex atl:w-full atl:gap-3 atl:data-[invalid=true]:text-destructive",
  {
    variants: {
      orientation: {
        vertical: ["atl:flex-col atl:[&>*]:w-full atl:[&>.sr-only]:w-auto"],
        horizontal: [
          "atl:flex-row atl:items-center",
          "atl:[&>[data-slot=field-label]]:flex-auto",
          "atl:has-[>[data-slot=field-content]]:items-start atl:has-[>[data-slot=field-content]]:[&>[role=checkbox],[role=radio]]:mt-px",
        ],
        responsive: [
          "atl:flex-col atl:@md/field-group:flex-row atl:@md/field-group:items-center atl:[&>*]:w-full atl:@md/field-group:[&>*]:w-auto atl:[&>.sr-only]:w-auto",
          "atl:@md/field-group:[&>[data-slot=field-label]]:flex-auto",
          "atl:@md/field-group:has-[>[data-slot=field-content]]:items-start atl:@md/field-group:has-[>[data-slot=field-content]]:[&>[role=checkbox],[role=radio]]:mt-px",
        ],
      },
    },
    defaultVariants: {
      orientation: "vertical",
    },
  }
)

function Field({
  className,
  orientation = "vertical",
  ...props
}) {
  return (
    <div
      role="group"
      data-slot="field"
      data-orientation={orientation}
      className={cn(fieldVariants({ orientation }), className)}
      {...props}
    />
  )
}

function FieldContent({
  className,
  ...props
}) {
  return (
    <div
      data-slot="field-content"
      className={cn(
        "atl:group/field-content atl:flex atl:flex-1 atl:flex-col atl:gap-1.5 atl:leading-snug",
        className
      )}
      {...props}
    />
  )
}

function FieldLabel({
  className,
  ...props
}) {
  return (
    <Label
      data-slot="field-label"
      className={cn(
        "atl:group/field-label atl:peer/field-label atl:flex atl:w-fit atl:gap-2 atl:leading-snug atl:group-data-[disabled=true]/field:opacity-50",
        "atl:has-[>[data-slot=field]]:w-full atl:has-[>[data-slot=field]]:flex-col atl:has-[>[data-slot=field]]:rounded-md atl:has-[>[data-slot=field]]:border atl:[&>*]:data-[slot=field]:p-4",
        "atl:has-data-[state=checked]:border-primary atl:has-data-[state=checked]:bg-primary/5 atl:dark:has-data-[state=checked]:bg-primary/10",
        className
      )}
      {...props}
    />
  )
}

function FieldTitle({
  className,
  ...props
}) {
  return (
    <div
      data-slot="field-label"
      className={cn(
        "atl:flex atl:w-fit atl:items-center atl:gap-2 atl:text-sm atl:leading-snug atl:font-medium atl:group-data-[disabled=true]/field:opacity-50",
        className
      )}
      {...props}
    />
  )
}

function FieldDescription({
  className,
  ...props
}) {
  return (
    <p
      data-slot="field-description"
      className={cn(
        "atl:text-sm atl:leading-normal atl:font-normal atl:text-muted-foreground atl:group-has-[[data-orientation=horizontal]]/field:text-balance",
        "atl:last:mt-0 atl:nth-last-2:-mt-1 atl:[[data-variant=legend]+&]:-mt-1.5",
        "atl:[&>a]:underline atl:[&>a]:underline-offset-4 atl:[&>a:hover]:text-primary",
        className
      )}
      {...props}
    />
  )
}

function FieldSeparator({
  children,
  className,
  ...props
}) {
  return (
    <div
      data-slot="field-separator"
      data-content={!!children}
      className={cn(
        "atl:relative atl:-my-2 atl:h-5 atl:text-sm atl:group-data-[variant=outline]/field-group:-mb-2",
        className
      )}
      {...props}
    >
      <Separator className="atl:absolute atl:inset-0 atl:top-1/2" />
      {children && (
        <span
          className="atl:relative atl:mx-auto atl:block atl:w-fit atl:bg-background atl:px-2 atl:text-muted-foreground"
          data-slot="field-separator-content"
        >
          {children}
        </span>
      )}
    </div>
  )
}

function FieldError({
  className,
  children,
  errors,
  ...props
}) {
  const content = useMemo(() => {
    if (children) {
      return children
    }

    if (!errors?.length) {
      return null
    }

    const uniqueErrors = [
      ...new Map(errors.map((error) => [error?.message, error])).values(),
    ]

    if (uniqueErrors?.length == 1) {
      return uniqueErrors[0]?.message
    }

    return (
      <ul className="atl:ml-4 atl:flex atl:list-disc atl:flex-col atl:gap-1">
        {uniqueErrors.map(
          (error, index) =>
            error?.message && <li key={index}>{error.message}</li>
        )}
      </ul>
    )
  }, [children, errors])

  if (!content) {
    return null
  }

  return (
    <div
      role="alert"
      data-slot="field-error"
      className={cn("atl:text-sm atl:font-normal atl:text-destructive", className)}
      {...props}
    >
      {content}
    </div>
  )
}

export {
  Field,
  FieldLabel,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLegend,
  FieldSeparator,
  FieldSet,
  FieldContent,
  FieldTitle,
}
