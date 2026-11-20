import type { CSSProperties, ReactNode } from "react";
import { cn } from "cn";

// The shell is viewport-high: the header stays put and the body scrolls under it.
// The body's inner column is at least the body's height. A child marked mw-fill
// (a Chat, a Split; one level down, through the renderer's display:contents
// wrapper) gets a zero flex basis here, so it fills what is left instead of
// growing with its content; everything else scrolls as usual.
// The body is what places anything in it that is taken out of the flow,
// an element hidden for a screen reader for one. Placed by something
// outside it, such an element would reach as far down as it stands in the
// page and make the window itself scroll, with nothing to show.
export const pageBodyClass = (padding: unknown) =>
  cn("mw-shell-body relative min-h-0 grow overflow-y-auto", padding !== false && "p-6");

export const PageBody = ({
  className,
  style,
  children,
}: {
  className: string;
  style?: CSSProperties;
  children: ReactNode;
}) => (
  <div className={cn("mx-auto flex min-h-full w-full flex-col [&>*>.mw-fill]:basis-0", className)} style={style}>
    {children}
  </div>
);

