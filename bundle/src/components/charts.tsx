// Charts are a chunk of their own: recharts loads the first time a page draws
// a chart. The renderers here hold the place at the chart's height until it
// has arrived, and draw the chart in the same pass once it has.

import { useEffect, useState } from "react";
import type { Renderer } from "../render";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "cn";

type Charts = typeof import("./charts-inner");

// The chart code once it is here, and the one request for it. A request that
// failed is forgotten, so the next chart to be drawn asks again.
let charts: Charts | null = null;
let asked: Promise<Charts> | null = null;

function ask(): Promise<Charts> {
  asked ??= import("./charts-inner").then(
    (m) => (charts = m),
    (err) => {
      asked = null;
      throw err;
    },
  );
  return asked;
}

// The chart code, or null while it is on its way. This is not a Suspense
// boundary with a lazy component: React keeps a fallback it has shown on
// screen for 300 ms, so a chart whose code arrived in ten would wait out the
// rest behind its placeholder. A failure is thrown while rendering, for the
// boundary around the node to show.
function useCharts(): Charts | null {
  const [here, setHere] = useState(charts);
  const [failed, setFailed] = useState<unknown>(null);
  useEffect(() => {
    if (here) return;
    let live = true;
    ask().then(
      (m) => live && setHere(m),
      (err) => live && setFailed(err),
    );
    return () => {
      live = false;
    };
  }, [here]);
  if (failed) throw failed;
  return here;
}

export type ChartKind = "bar" | "line" | "area" | "pie";

export function chartHeight(props: Record<string, unknown>): number {
  return typeof props.height === "number" && props.height > 0 ? props.height : 256;
}

function chart(kind: ChartKind): Renderer {
  return ({ props, emit }) => {
    const code = useCharts();
    return (
      <div className={cn("w-full", props.cls as string)}>
        {code ? <code.Chart kind={kind} props={props} emit={emit} /> : <Skeleton className="w-full" style={{ height: chartHeight(props) }} />}
      </div>
    );
  };
}

export const BarChart = chart("bar");
export const LineChart = chart("line");
export const AreaChart = chart("area");
export const PieChart = chart("pie");

export function Sparkline({ values }: { values: number[] }) {
  const code = useCharts();
  return code ? <code.Sparkline values={values} /> : <div className="h-8 w-24" />;
}
