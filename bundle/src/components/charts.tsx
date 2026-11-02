// Charts are a lazy chunk: recharts loads the first time a page draws one.
// The renderers here hold the place at the chart's height until it arrives.

import { lazy, Suspense } from "react";
import type { Renderer } from "../render";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "cn";

const Inner = lazy(() => import("./charts-inner").then((m) => ({ default: m.Chart })));
const InnerSparkline = lazy(() => import("./charts-inner").then((m) => ({ default: m.Sparkline })));

export type ChartKind = "bar" | "line" | "area" | "pie";

export function chartHeight(props: Record<string, unknown>): number {
  return typeof props.height === "number" && props.height > 0 ? props.height : 256;
}

function chart(kind: ChartKind): Renderer {
  return ({ props, emit }) => (
    <div className={cn("w-full", props.cls as string)}>
      <Suspense fallback={<Skeleton className="w-full" style={{ height: chartHeight(props) }} />}>
        <Inner kind={kind} props={props} emit={emit} />
      </Suspense>
    </div>
  );
}

export const BarChart = chart("bar");
export const LineChart = chart("line");
export const AreaChart = chart("area");
export const PieChart = chart("pie");

export function Sparkline({ values }: { values: number[] }) {
  return (
    <Suspense fallback={<div className="h-8 w-24" />}>
      <InnerSparkline values={values} />
    </Suspense>
  );
}
