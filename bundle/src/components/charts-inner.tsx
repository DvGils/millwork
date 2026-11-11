// The charts themselves, on recharts. One tooltip and one legend serve the
// three kinds, so every chart reads the same way: values lead, the series name
// follows, the mark's colour keys them.

import { useMemo, type ReactElement } from "react";
import {
  Area,
  AreaChart as RAreaChart,
  Bar,
  BarChart as RBarChart,
  CartesianGrid,
  Cell,
  Label,
  LabelList,
  Line,
  LineChart as RLineChart,
  Pie,
  PieChart as RPieChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ChartContainer, type ChartConfig } from "@/components/ui/chart";
import { formatNumber } from "../format";
import { cn } from "cn";
import {
  NEUTRAL,
  divergingBars,
  divergingColors,
  divergingRows,
  rekey,
  chartSlot,
  seriesColors,
  slot,
  valueAxis,
  valueExtent,
  type Row,
  type Series,
} from "../charts-data";
import { chartHeight, type ChartKind } from "./charts";

const BAR = 24;

interface TipProps {
  active?: boolean;
  label?: unknown;
  payload?: { payload: Row }[];
  series: Series[];
  colors: string[];
  format?: string | null;
}

function Tip({ active, label, payload, series, colors, format }: TipProps) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="grid min-w-32 gap-1.5 rounded-lg border border-border/50 bg-background px-2.5 py-1.5 text-xs shadow-xl">
      <div className="font-medium">{String(label ?? row.x ?? "")}</div>
      {series.map((s, i) => {
        const v = row[slot(i)];
        if (v === null || v === undefined) return null;
        return (
          <div key={s.key} className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 shrink-0 rounded-[2px]" style={{ background: colors[i] }} />
            <span className="flex-1 text-muted-foreground">{s.label}</span>
            <span className="font-mono font-medium tabular-nums text-foreground">{formatNumber(v, format)}</span>
          </div>
        );
      })}
    </div>
  );
}

function Legend({ series, colors, line }: { series: Series[]; colors: string[]; line: boolean }) {
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 pt-3 text-xs text-muted-foreground">
      {series.map((s, i) => (
        <div key={s.key} className="flex items-center gap-1.5">
          <span className={line ? "h-0.5 w-3 rounded-full" : "h-2 w-2 rounded-[2px]"} style={{ background: colors[i] }} />
          {s.label}
        </div>
      ))}
    </div>
  );
}

// The series name at the end of its line, instead of a number on every point.
// `last` is the last point with a value: a trailing gap has no place to sit.
function endLabel(text: string, last: number) {
  return (p: { x?: number; y?: number; index?: number }): ReactElement | null =>
    p.index === last && typeof p.x === "number" && typeof p.y === "number" ? (
      <text x={p.x + 6} y={p.y} dy={4} className="fill-foreground text-[10px]">
        {text}
      </text>
    ) : null;
}

// How wide a label is as the chart writes it, to keep that much room beside
// the plot. Without a canvas to measure on it is a guess by the character.
let ruler: CanvasRenderingContext2D | null | undefined;
function labelWidth(text: string): number {
  if (ruler === undefined) ruler = typeof document === "undefined" ? null : document.createElement("canvas").getContext("2d");
  if (!ruler) return text.length * 6.5;
  ruler.font = `10px ${getComputedStyle(document.body).fontFamily}`;
  return ruler.measureText(text).width;
}

export interface ChartProps {
  kind: ChartKind;
  props: Record<string, unknown>;
  emit: (name: string, payload?: unknown) => void;
}

interface Slice {
  x: unknown;
  value: number;
  other: boolean;
  color?: number;
}

// A pie: one slice per row, the theme's hues in row order, a folded tail in
// grey. The legend carries the names and the tooltip the value and the share;
// labels on the slices are the shares, left off a slice too thin to hold one.
function PieTip({ active, payload, format, total }: { active?: boolean; payload?: { payload: Slice & { fill: string } }[]; format?: string | null; total: number }) {
  if (!active || !payload?.length) return null;
  const s = payload[0].payload;
  return (
    <div className="grid min-w-32 gap-1.5 rounded-lg border border-border/50 bg-background px-2.5 py-1.5 text-xs shadow-xl">
      <div className="flex items-center gap-2">
        <span className="h-2.5 w-2.5 shrink-0 rounded-[2px]" style={{ background: s.fill }} />
        <span className="flex-1 text-muted-foreground">{String(s.x)}</span>
        <span className="font-mono font-medium tabular-nums text-foreground">{formatNumber(s.value, format)}</span>
      </div>
      <div className="text-right text-muted-foreground">{total > 0 ? `${Math.round((s.value / total) * 100)}%` : ""}</div>
    </div>
  );
}

function PieInner({ props, emit }: Omit<ChartProps, "kind">) {
  const slices = (props.data as Slice[] | undefined) ?? [];
  const format = props.format as string | null | undefined;
  const donut = Boolean(props.donut);
  const labels = Boolean(props.labels);
  const center = typeof props.center === "string" ? props.center : null;
  const total = slices.reduce((a, s) => a + s.value, 0);
  const colors = slices.map((s, i) => (s.other ? NEUTRAL : chartSlot(s, i)));
  const rows = slices.map((s, i) => ({ ...s, name: String(s.x), fill: colors[i] }));
  const series: Series[] = rows.map((r) => ({ key: r.name, label: r.name }));
  const showLegend = typeof props.legend === "boolean" ? props.legend : rows.length > 1;
  const click = props.on_click
    ? (d: unknown) => {
        const s = (d as { payload?: Slice })?.payload;
        if (s) emit("click", { x: s.x ?? null, value: s.value, share: total > 0 ? s.value / total : null });
      }
    : undefined;
  const share = (p: { percent?: number; x?: number; y?: number; textAnchor?: string }): ReactElement | null =>
    typeof p.percent === "number" && p.percent >= 0.04 && typeof p.x === "number" && typeof p.y === "number" ? (
      <text x={p.x} y={p.y} dy={4} textAnchor={p.textAnchor === "start" || p.textAnchor === "end" ? p.textAnchor : "middle"} className="fill-foreground text-[10px]">
        {`${Math.round(p.percent * 100)}%`}
      </text>
    ) : null;
  return (
    <div className="flex w-full flex-col" data-press={click ? "" : undefined}>
      <ChartContainer config={{}} className={cn("aspect-auto w-full", click && "cursor-pointer")} style={{ height: chartHeight(props) }}>
        <RPieChart margin={{ top: 8, right: labels ? 24 : 8, bottom: 8, left: labels ? 24 : 8 }} accessibilityLayer>
          <Tooltip content={<PieTip format={format} total={total} />} isAnimationActive={false} />
          <Pie
            data={rows}
            dataKey="value"
            nameKey="name"
            innerRadius={donut ? "58%" : 0}
            outerRadius={labels ? "78%" : "92%"}
            paddingAngle={rows.length > 1 ? 1.5 : 0}
            stroke="var(--background)"
            strokeWidth={2}
            isAnimationActive={false}
            label={labels ? share : false}
            labelLine={false}
            onClick={click}
          >
            {colors.map((fill, i) => (
              <Cell key={i} fill={fill} />
            ))}
            {donut && center ? (
              <Label
                position="center"
                content={(p: { x?: number; y?: number }) =>
                  typeof p.x === "number" && typeof p.y === "number" ? (
                    <text x={p.x} y={p.y} dy={6} textAnchor="middle" className="fill-foreground text-lg font-semibold tabular-nums">
                      {center}
                    </text>
                  ) : null
                }
              />
            ) : null}
          </Pie>
        </RPieChart>
      </ChartContainer>
      {showLegend && rows.length > 0 ? <Legend series={series} colors={colors} line={false} /> : null}
    </div>
  );
}

export function Chart({ kind, props, emit }: ChartProps) {
  if (kind === "pie") return <PieInner props={props} emit={emit} />;
  const series = (props.series as Series[] | undefined) ?? [];
  const raw = (props.data as Row[] | undefined) ?? [];
  const format = props.format as string | null | undefined;
  const stacked = (props.stacked as boolean | "percent" | undefined) ?? false;
  const horizontal = kind === "bar" && Boolean(props.horizontal);
  const diverging = kind === "bar" && Boolean(props.diverging);
  const curve = Boolean(props.curve);
  const dots = Boolean(props.dots);
  const labels = Boolean(props.labels);
  const emphasisKey = typeof props.emphasis === "string" ? props.emphasis : null;
  const emphasis = emphasisKey === null ? null : series.findIndex((s) => s.key === emphasisKey);
  const n = series.length;
  const rows = useMemo(() => {
    const keyed = rekey(raw, series);
    return diverging ? divergingRows(keyed, n) : keyed;
  }, [raw, series, diverging, n]);
  const colors = useMemo(
    () => (diverging ? divergingColors(n) : seriesColors(series, emphasis === -1 ? null : emphasis)),
    [diverging, n, series, emphasis],
  );
  const config = useMemo(
    () => Object.fromEntries(series.map((s, i) => [slot(i), { label: s.label, color: colors[i] }])) as ChartConfig,
    [series, colors],
  );
  const showLegend = typeof props.legend === "boolean" ? props.legend : n > 1;
  const lastPoint = (i: number) => {
    for (let j = rows.length - 1; j >= 0; j--) if (typeof rows[j][slot(i)] === "number") return j;
    return -1;
  };
  const valueFormat = stacked === "percent" ? "percent" : format;
  // A diverging chart stacks one side below zero; its axis still reads as counts.
  const tick = (v: unknown) => formatNumber(diverging ? Math.abs(Number(v)) : v, valueFormat, true);
  // Where the value axis runs and where its ticks are: round steps, a
  // baseline at zero for bars, the app's own range on a line or an area.
  const yRange = (props.y_range as [number | null, number | null] | null | undefined) ?? null;
  // Counts, and money on an axis, are labeled without decimals.
  const whole = valueFormat === "integer" || valueFormat === "currency";
  const axis = useMemo(() => {
    if (stacked === "percent") return { domain: [0, 1] as [number, number], ticks: [0, 0.25, 0.5, 0.75, 1] };
    if (diverging) {
      const extent = valueExtent(rows, n, true);
      const reach = Math.max(Math.abs(extent?.[0] ?? 0), Math.abs(extent?.[1] ?? 0));
      return valueAxis([-reach, reach], null, true, whole);
    }
    return valueAxis(valueExtent(rows, n, Boolean(stacked)), yRange, kind === "bar", whole);
  }, [rows, n, stacked, diverging, kind, yRange, whole]);

  const click = props.on_click
    ? (row: Row, index: number | null) =>
        emit("click", {
          x: row.x ?? null,
          series: index === null ? null : series[index].key,
          value: index === null ? null : (row[slot(index)] ?? null),
          values: Object.fromEntries(series.map((s, j) => [s.key, row[slot(j)] ?? null])),
        })
    : null;
  // A click anywhere on a line or area chart means the x under the pointer.
  const chartClick = click && kind !== "bar"
    ? (state: unknown) => {
        const i = (state as { activeTooltipIndex?: unknown } | null)?.activeTooltipIndex;
        const at = typeof i === "number" ? i : typeof i === "string" ? Number(i) : NaN;
        if (Number.isInteger(at) && rows[at]) click(rows[at], null);
      }
    : undefined;
  const barClick = (index: number) =>
    click ? (d: unknown) => click((d as { payload?: Row })?.payload ?? {}, index) : undefined;

  const categoryAxis = horizontal ? (
    <YAxis type="category" dataKey="x" tickLine={false} axisLine={false} width="auto" tickMargin={6} />
  ) : (
    <XAxis dataKey="x" tickLine={false} axisLine={false} tickMargin={8} />
  );
  const numberAxis = horizontal ? (
    <XAxis
      type="number"
      tickLine={false}
      axisLine={false}
      tickFormatter={tick}
      domain={axis.domain}
      ticks={axis.ticks}
      allowDataOverflow
    />
  ) : (
    <YAxis
      tickLine={false}
      axisLine={false}
      width="auto"
      tickFormatter={tick}
      domain={axis.domain}
      ticks={axis.ticks}
      allowDataOverflow
    />
  );
  const tooltip = (
    <Tooltip
      cursor={kind === "bar" ? { fill: "var(--muted)" } : { stroke: "var(--border)" }}
      content={<Tip series={series} colors={colors} format={format} />}
      isAnimationActive={false}
    />
  );
  // Room for the labels that are written outside the plot: a series name
  // after the end of its line, a value after the end of a lying bar, and a
  // value above a standing one, whose bar may reach the top of the axis.
  const beside = useMemo(() => {
    if (!labels) return 12;
    let texts: string[] = [];
    if (kind !== "bar") texts = series.map((s) => s.label);
    else if (horizontal && !stacked && !diverging)
      texts = rows.flatMap((row) => series.map((_, i) => formatNumber(row[slot(i)], format)));
    return 12 + Math.ceil(Math.max(0, ...texts.map(labelWidth)));
  }, [labels, kind, horizontal, stacked, diverging, rows, series, format]);
  const above = labels && kind === "bar" && !horizontal && !stacked && !diverging ? 20 : 8;
  const common = {
    data: rows,
    layout: horizontal ? ("vertical" as const) : ("horizontal" as const),
    // Stacks keep positives above and negatives below the axis; "none"
    // would draw a negative segment inside the positive one.
    stackOffset: stacked === "percent" ? ("expand" as const) : diverging || stacked ? ("sign" as const) : ("none" as const),
    margin: { top: above, right: beside, bottom: 0, left: 0 },
    accessibilityLayer: true,
    onClick: chartClick,
    className: click ? "cursor-pointer" : undefined,
  };

  let plot: ReactElement;
  if (kind === "bar") {
    const bars = diverging
      ? divergingBars(n).map(({ index, dataKey }) => (
          <Bar
            key={dataKey}
            dataKey={dataKey}
            stackId="d"
            fill={`var(--color-${slot(index)})`}
            stroke="var(--background)"
            strokeWidth={1}
            maxBarSize={BAR}
            isAnimationActive={false}
            onClick={barClick(index)}
          />
        ))
      : series.map((s, i) => (
          <Bar
            key={s.key}
            dataKey={slot(i)}
            stackId={stacked ? "a" : undefined}
            fill={`var(--color-${slot(i)})`}
            radius={stacked ? 0 : horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]}
            stroke={stacked ? "var(--background)" : undefined}
            strokeWidth={stacked ? 1 : 0}
            maxBarSize={BAR}
            isAnimationActive={false}
            onClick={barClick(i)}
          >
            {labels ? (
              <LabelList
                dataKey={slot(i)}
                position={stacked ? "center" : horizontal ? "right" : "top"}
                formatter={(v: unknown) => formatNumber(v, format)}
                className="fill-foreground text-[10px]"
              />
            ) : null}
          </Bar>
        ));
    plot = (
      <RBarChart {...common} barGap={2} barCategoryGap="20%">
        <CartesianGrid vertical={horizontal} horizontal={!horizontal} />
        {categoryAxis}
        {numberAxis}
        {tooltip}
        {bars}
      </RBarChart>
    );
  } else if (kind === "line") {
    plot = (
      <RLineChart {...common}>
        <CartesianGrid vertical={false} />
        {categoryAxis}
        {numberAxis}
        {tooltip}
        {series.map((s, i) => (
          <Line
            key={s.key}
            type={curve ? "monotone" : "linear"}
            dataKey={slot(i)}
            stroke={`var(--color-${slot(i)})`}
            strokeWidth={2}
            dot={dots ? { r: 3, strokeWidth: 2, stroke: "var(--background)", fill: `var(--color-${slot(i)})` } : false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--background)" }}
            isAnimationActive={false}
          >
            {labels ? <LabelList dataKey={slot(i)} content={endLabel(s.label, lastPoint(i))} /> : null}
          </Line>
        ))}
      </RLineChart>
    );
  } else {
    plot = (
      <RAreaChart {...common}>
        <CartesianGrid vertical={false} />
        {categoryAxis}
        {numberAxis}
        {tooltip}
        {series.map((s, i) => (
          <Area
            key={s.key}
            type={curve ? "monotone" : "linear"}
            dataKey={slot(i)}
            stackId={stacked ? "a" : undefined}
            stroke={`var(--color-${slot(i)})`}
            strokeWidth={2}
            fill={`var(--color-${slot(i)})`}
            fillOpacity={stacked ? 0.5 : 0.2}
            activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--background)" }}
            isAnimationActive={false}
          >
            {labels ? <LabelList dataKey={slot(i)} content={endLabel(s.label, lastPoint(i))} /> : null}
          </Area>
        ))}
      </RAreaChart>
    );
  }

  return (
    <div className="flex w-full flex-col" data-press={click ? "" : undefined}>
      <ChartContainer config={config} className="aspect-auto w-full" style={{ height: chartHeight(props) }}>
        {plot}
      </ChartContainer>
      {showLegend && n > 0 ? <Legend series={series} colors={colors} line={kind === "line"} /> : null}
    </div>
  );
}

// A Stat's trend: the line recedes, the last point is the one that matters.
export function Sparkline({ values }: { values: number[] }) {
  const data = values.map((v, i) => ({ i, v }));
  const last = data.length - 1;
  return (
    <RLineChart data={data} width={96} height={32} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
      <Line
        dataKey="v"
        stroke="var(--muted-foreground)"
        strokeWidth={1.5}
        isAnimationActive={false}
        dot={(p: { cx?: number; cy?: number; index?: number }) =>
          p.index === last && typeof p.cx === "number" && typeof p.cy === "number" ? (
            <circle key="last" cx={p.cx} cy={p.cy} r={3} fill="var(--primary)" stroke="var(--background)" strokeWidth={2} />
          ) : (
            <g key={p.index} />
          )
        }
      />
    </RLineChart>
  );
}
