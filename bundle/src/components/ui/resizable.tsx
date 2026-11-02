// Resizable panes: a group lays panels out along one axis, a handle between
// two panels moves their shared edge with the pointer or the arrow keys, and a
// collapsible panel folds away when dragged under half its minimum.
import * as React from "react"
import { cn } from "cn"

type Spec = { defaultSize?: number; minSize: number; collapsible: boolean; collapsedSize: number }

type Group = {
  orientation: "horizontal" | "vertical"
  sizes: number[]
  element: React.RefObject<HTMLDivElement | null>
  register: (index: number, spec: Spec) => () => void
  // The first panel of the pair gets ``size`` percent, as far as the minimums
  // allow; the second takes the rest. A drag works from where it started, so
  // a panel passes the point where it collapses instead of stopping at its minimum.
  resize: (handle: number, size: number) => void
  move: (handle: number, deltaPercent: number) => void
  // What the handle's first panel can be dragged between.
  reach: (handle: number) => [number, number]
  specs: React.RefObject<(Spec | undefined)[]>
}

const Context = React.createContext<Group | null>(null)

function useGroup(): Group {
  const ctx = React.useContext(Context)
  if (!ctx) throw new Error("a ResizablePanel needs a ResizablePanelGroup")
  return ctx
}

function percent(value: string | number | undefined): number | undefined {
  if (value === undefined) return undefined
  const n = typeof value === "number" ? value : parseFloat(value)
  return Number.isFinite(n) ? n : undefined
}

// Panels without a size share what the sized ones leave; sizes that do not
// add up to the whole are scaled so they do.
function layout(specs: (Spec | undefined)[]): number[] {
  const named = specs.reduce<number>((a, s) => a + (s?.defaultSize ?? 0), 0)
  const free = specs.filter((s) => s && s.defaultSize === undefined).length
  const scale = free === 0 && named > 0 ? 100 / named : named > 100 ? 100 / named : 1
  const each = free ? Math.max(0, 100 - named * scale) / free : 0
  return specs.map((s) => (s?.defaultSize === undefined ? each : s.defaultSize * scale))
}

function ResizablePanelGroup({
  orientation = "horizontal",
  className,
  children,
  ...props
}: React.ComponentProps<"div"> & { orientation?: "horizontal" | "vertical" }) {
  const element = React.useRef<HTMLDivElement | null>(null)
  const specs = React.useRef<(Spec | undefined)[]>([])
  const [sizes, setSizes] = React.useState<number[]>([])
  const register = React.useCallback((index: number, spec: Spec) => {
    const fresh = specs.current[index] === undefined
    specs.current[index] = spec
    // A panel that comes or goes relays the whole group; one that re-renders
    // or changes its limits keeps the sizes the reader dragged to.
    if (fresh) setSizes((old) => (old.length === specs.current.length && old[index] !== undefined ? old : layout(specs.current)))
    return () => {
      specs.current[index] = undefined
      // Whether the panel is gone or only re-registering shows once this
      // commit's effects have run.
      queueMicrotask(() => {
        if (specs.current[index] !== undefined) return
        while (specs.current.length && specs.current[specs.current.length - 1] === undefined) specs.current.pop()
        setSizes(layout(specs.current))
      })
    }
  }, [])
  const resize = React.useCallback((handle: number, size: number) => {
    setSizes((old) => {
      const a = handle, b = handle + 1
      const sa = specs.current[a], sb = specs.current[b]
      if (old[a] === undefined || old[b] === undefined || !sa || !sb) return old
      const total = old[a] + old[b]
      const fit = (wanted: number, spec: Spec, other: Spec) => {
        const room = total - (other.collapsible ? other.collapsedSize : other.minSize)
        let s = Math.min(wanted, room)
        if (spec.collapsible && s < spec.minSize / 2) s = spec.collapsedSize
        else if (s < spec.minSize) s = spec.minSize
        return Math.max(0, Math.min(total, s))
      }
      const sizeB = fit(total - fit(size, sa, sb), sb, sa)
      const next = [...old]
      next[a] = total - sizeB
      next[b] = sizeB
      return next
    })
  }, [])
  const move = React.useCallback((handle: number, delta: number) => {
    const current = sizesRef.current[handle]
    const spec = specs.current[handle]
    if (current === undefined || !spec) return
    // A step out of a collapsed panel opens it to its minimum.
    const collapsed = spec.collapsible && current <= spec.collapsedSize
    resize(handle, collapsed && delta > 0 ? spec.minSize : current + delta)
  }, [resize])
  const sizesRef = React.useRef(sizes)
  sizesRef.current = sizes
  const reach = React.useCallback((handle: number): [number, number] => {
    const a = specs.current[handle], b = specs.current[handle + 1]
    const total = (sizesRef.current[handle] ?? 0) + (sizesRef.current[handle + 1] ?? 0)
    if (!a || !b) return [0, 100]
    return [a.collapsible ? a.collapsedSize : a.minSize, total - (b.collapsible ? b.collapsedSize : b.minSize)]
  }, [])
  const value = React.useMemo(
    () => ({ orientation, sizes, element, register, resize, move, reach, specs }),
    [orientation, sizes, register, resize, move, reach]
  )
  return (
    <Context.Provider value={value}>
      <div
        ref={element}
        data-slot="resizable-panel-group"
        data-orientation={orientation}
        className={cn("flex h-full w-full data-[orientation=vertical]:flex-col", className)}
        {...props}
      >
        {children}
      </div>
    </Context.Provider>
  )
}

// A panel or a handle is the nth of its kind among the group's children.
function useIndex(ref: React.RefObject<HTMLElement | null>, slot: string): number | null {
  const [index, setIndex] = React.useState<number | null>(null)
  React.useLayoutEffect(() => {
    const el = ref.current
    const parent = el?.parentElement
    if (!el || !parent) return
    const kin = Array.from(parent.children).filter((c) => (c as HTMLElement).dataset.slot === slot)
    setIndex(kin.indexOf(el))
  })
  return index
}

function ResizablePanel({
  defaultSize,
  minSize,
  collapsible = false,
  collapsedSize = 0,
  className,
  style,
  children,
  ...props
}: React.ComponentProps<"div"> & {
  defaultSize?: string | number
  minSize?: string | number
  collapsible?: boolean
  collapsedSize?: number
}) {
  const group = useGroup()
  const ref = React.useRef<HTMLDivElement | null>(null)
  const index = useIndex(ref, "resizable-panel")
  const size0 = percent(defaultSize)
  const min = percent(minSize) ?? 0
  React.useLayoutEffect(() => {
    if (index === null) return
    return group.register(index, { defaultSize: size0, minSize: min, collapsible, collapsedSize })
  }, [group.register, index, size0, min, collapsible, collapsedSize])
  const size = index === null ? undefined : group.sizes[index]
  const collapsed = collapsible && size !== undefined && size <= collapsedSize
  return (
    <div
      ref={ref}
      data-slot="resizable-panel"
      data-collapsed={collapsed || undefined}
      className={cn("min-h-0 min-w-0", className)}
      style={{ ...style, flex: `0 1 ${size ?? 0}%`, overflow: collapsed ? "hidden" : undefined }}
      {...props}
    >
      {children}
    </div>
  )
}

function ResizableHandle({
  withHandle,
  className,
  ...props
}: React.ComponentProps<"div"> & { withHandle?: boolean }) {
  const group = useGroup()
  const ref = React.useRef<HTMLDivElement | null>(null)
  const index = useIndex(ref, "resizable-handle")
  const vertical = group.orientation === "vertical"
  const drag = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 || index === null) return
    const rect = group.element.current?.getBoundingClientRect()
    const span = rect ? (vertical ? rect.height : rect.width) : 0
    if (!span) return
    const target = e.currentTarget
    target.focus()
    target.setPointerCapture(e.pointerId)
    const selection = document.body.style.userSelect
    document.body.style.userSelect = "none"
    const origin = vertical ? e.clientY : e.clientX
    const startSize = group.sizes[index] ?? 0
    const onMove = (ev: PointerEvent) => {
      const now = vertical ? ev.clientY : ev.clientX
      group.resize(index, startSize + ((now - origin) / span) * 100)
    }
    const onUp = () => {
      document.body.style.userSelect = selection
      target.removeEventListener("pointermove", onMove)
      target.removeEventListener("pointerup", onUp)
      target.removeEventListener("pointercancel", onUp)
      target.removeEventListener("lostpointercapture", onUp)
    }
    target.addEventListener("pointermove", onMove)
    target.addEventListener("pointerup", onUp)
    target.addEventListener("pointercancel", onUp)
    target.addEventListener("lostpointercapture", onUp)
    e.preventDefault()
  }
  // Arrows step the edge, Home and End take it as far as it goes, Enter folds
  // a collapsible panel away and brings it back to where it was.
  const remembered = React.useRef<number | null>(null)
  const keys = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (index === null) return
    const back = vertical ? "ArrowUp" : "ArrowLeft"
    const forth = vertical ? "ArrowDown" : "ArrowRight"
    const [low, high] = group.reach(index)
    const size = group.sizes[index] ?? 0
    const spec = group.specs.current?.[index]
    if (e.key === back) group.move(index, -5)
    else if (e.key === forth) group.move(index, 5)
    else if (e.key === "Home") group.resize(index, low)
    else if (e.key === "End") group.resize(index, high)
    else if (e.key === "Enter" && spec?.collapsible) {
      if (size <= spec.collapsedSize) group.resize(index, remembered.current ?? spec.minSize)
      else {
        remembered.current = size
        group.resize(index, spec.collapsedSize)
      }
    } else return
    e.preventDefault()
  }
  const size = index === null ? undefined : group.sizes[index]
  const [low, high] = index === null ? [0, 100] : group.reach(index)
  return (
    <div
      ref={ref}
      role="separator"
      tabIndex={0}
      aria-orientation={vertical ? "horizontal" : "vertical"}
      aria-valuenow={size !== undefined ? Math.round(size) : undefined}
      aria-valuemin={Math.round(low)}
      aria-valuemax={Math.round(high)}
      data-slot="resizable-handle"
      onPointerDown={drag}
      onKeyDown={keys}
      className={cn(
        "relative flex w-px shrink-0 touch-none items-center justify-center bg-border ring-offset-background after:absolute after:inset-y-0 after:left-1/2 after:w-2 after:-translate-x-1/2 focus-visible:ring-1 focus-visible:ring-ring focus-visible:outline-hidden",
        vertical
          ? "h-px w-full cursor-row-resize after:inset-x-0 after:left-0 after:h-2 after:w-full after:translate-x-0 after:-translate-y-1/2 [&>div]:rotate-90"
          : "cursor-col-resize",
        className
      )}
      {...props}
    >
      {withHandle && <div className="z-10 flex h-6 w-1 shrink-0 rounded-lg bg-border" />}
    </div>
  )
}

export { ResizableHandle, ResizablePanel, ResizablePanelGroup }
