// A viewport that stays at the end while new content arrives, until the
// reader scrolls up; a button brings them back to the end.
import * as React from "react"
import { cn } from "cn"

import { Button } from "@/components/ui/button"
import { ArrowDownIcon } from "lucide-react"
import { t } from "../../theme"

const END_SLACK = 12 // px from the end that still counts as being at the end
// How long after a wheel, touch, pointer or key on the viewport a scroll
// event counts as the reader's own. Scrolls the page makes itself, smooth
// or not, never end the following; only the reader does.
const INTENT_MS = 1000

type Scroller = {
  viewport: React.RefObject<HTMLDivElement | null>
  atEnd: boolean
  setAtEnd: (v: boolean) => void
  sticky: React.MutableRefObject<boolean>
  intent: React.MutableRefObject<number>
  scrollToEnd: (smooth?: boolean) => void
  follow: () => void
}

const Context = React.createContext<Scroller | null>(null)

function useScroller(): Scroller {
  const ctx = React.useContext(Context)
  if (!ctx) throw new Error("MessageScroller parts need a MessageScrollerProvider")
  return ctx
}

function MessageScrollerProvider({
  autoScroll = true,
  defaultScrollPosition = "end",
  children,
}: {
  autoScroll?: boolean
  defaultScrollPosition?: "start" | "end"
  children: React.ReactNode
}) {
  const viewport = React.useRef<HTMLDivElement | null>(null)
  const [atEnd, setAtEnd] = React.useState(true)
  const sticky = React.useRef(autoScroll && defaultScrollPosition === "end")
  const intent = React.useRef(0)
  const scrollToEnd = React.useCallback((smooth = true) => {
    const el = viewport.current
    if (!el) return
    sticky.current = true
    intent.current = 0
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" })
  }, [])
  // Keep the end in view while the reader has not scrolled away from it.
  const follow = React.useCallback(() => {
    const el = viewport.current
    if (el && sticky.current) el.scrollTop = el.scrollHeight
  }, [])
  const value = React.useMemo(
    () => ({ viewport, atEnd, setAtEnd, sticky, intent, scrollToEnd, follow }),
    [atEnd, scrollToEnd, follow]
  )
  return <Context.Provider value={value}>{children}</Context.Provider>
}

function MessageScroller({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="message-scroller"
      className={cn(
        "group/message-scroller relative flex size-full min-h-0 flex-col overflow-hidden",
        className
      )}
      {...props}
    />
  )
}

function MessageScrollerViewport({ className, onScroll, ...props }: React.ComponentProps<"div">) {
  const { viewport, sticky, setAtEnd, atEnd, intent, follow } = useScroller()
  const atEndRef = React.useRef(atEnd)
  atEndRef.current = atEnd
  const measure = React.useCallback(() => {
    const el = viewport.current
    if (!el) return
    const end = el.scrollHeight - el.scrollTop - el.clientHeight <= END_SLACK
    if (end) sticky.current = true
    else if (Date.now() - intent.current < INTENT_MS) sticky.current = false
    if (end !== atEndRef.current) setAtEnd(end)
  }, [viewport, sticky, intent, setAtEnd])
  const scrolled = (e: React.UIEvent<HTMLDivElement>) => {
    measure()
    onScroll?.(e)
  }
  const touched = () => {
    intent.current = Date.now()
  }
  // Content that grows on its own, an image that loads or a step that unfolds,
  // keeps the reader at the end; growth from a render is followed by Content.
  // A viewport that shrinks, the composer growing under it, is measured again.
  React.useLayoutEffect(() => {
    const el = viewport.current
    const content = el?.firstElementChild
    if (!el || !content) return
    follow()
    const ro = new ResizeObserver(() => {
      follow()
      measure()
    })
    ro.observe(content)
    ro.observe(el)
    return () => ro.disconnect()
  }, [viewport, follow, measure])
  return (
    <div
      ref={viewport}
      role="region"
      aria-label={t("messages")}
      tabIndex={0}
      data-slot="message-scroller-viewport"
      onScroll={scrolled}
      onWheel={touched}
      onTouchMove={touched}
      onPointerDown={touched}
      onKeyDown={touched}
      className={cn(
        "size-full min-h-0 min-w-0 scroll-fade-b scrollbar-thin scrollbar-gutter-stable overflow-y-auto overscroll-contain contain-content",
        className
      )}
      {...props}
    />
  )
}

function MessageScrollerContent({ className, ...props }: React.ComponentProps<"div">) {
  const { follow } = useScroller()
  // After every commit: a streamed delta, a new message, an unfolded step.
  React.useLayoutEffect(follow)
  return (
    <div
      role="log"
      aria-relevant="additions"
      data-slot="message-scroller-content"
      className={cn("flex h-max min-h-full flex-col gap-6", className)}
      {...props}
    />
  )
}

function MessageScrollerItem({
  className,
  messageId,
  ...props
}: React.ComponentProps<"div"> & { messageId?: string }) {
  return (
    <div
      data-slot="message-scroller-item"
      data-message-id={messageId}
      className={cn(
        "min-w-0 shrink-0 [contain-intrinsic-size:auto_10rem] [content-visibility:auto]",
        className
      )}
      {...props}
    />
  )
}

function MessageScrollerButton({
  className,
  variant = "secondary",
  size = "icon-sm",
  ...props
}: Omit<React.ComponentProps<typeof Button>, "onClick">) {
  const { atEnd, scrollToEnd } = useScroller()
  return (
    <Button
      data-slot="message-scroller-button"
      data-active={!atEnd}
      inert={atEnd}
      tabIndex={atEnd ? -1 : 0}
      variant={variant}
      size={size}
      onClick={(e) => {
        scrollToEnd()
        e.currentTarget.blur()
      }}
      className={cn(
        "absolute inset-s-1/2 bottom-4 -translate-x-1/2 border-border bg-background text-foreground transition-[translate,scale,opacity] duration-200 hover:bg-muted hover:text-foreground data-[active=false]:pointer-events-none data-[active=false]:translate-y-full data-[active=false]:scale-95 data-[active=false]:opacity-0 data-[active=true]:translate-y-0 data-[active=true]:scale-100 data-[active=true]:opacity-100 rtl:translate-x-1/2",
        className
      )}
      {...props}
    >
      <ArrowDownIcon />
      <span className="sr-only">{t("scroll_to_end")}</span>
    </Button>
  )
}

export {
  MessageScrollerProvider,
  MessageScroller,
  MessageScrollerViewport,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerButton,
}
