import * as React from "react"
import { cn } from "cn"
import { LONG_TEXT, spellcheckForLength } from "../../lib"

// The height follows `rows` unless a class asks for `field-sizing-content`,
// and then it stops at most of the viewport, so a long paste scrolls inside
// the field instead of stretching the page.
function Textarea({ className, onInput, value, defaultValue, ...props }: React.ComponentProps<"textarea">) {
  const initial = typeof value === "string" ? value : typeof defaultValue === "string" ? defaultValue : ""
  return (
    <textarea
      data-slot="textarea"
      value={value}
      defaultValue={defaultValue}
      spellCheck={initial.length > LONG_TEXT ? false : props.spellCheck}
      onInput={(e) => {
        spellcheckForLength(e.currentTarget)
        onInput?.(e)
      }}
      className={cn(
        "flex max-h-[60dvh] min-h-16 w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-base transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:bg-input/50 disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 md:text-sm dark:bg-input/30 dark:disabled:bg-input/80 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40",
        className
      )}
      {...props}
    />
  )
}

export { Textarea }
