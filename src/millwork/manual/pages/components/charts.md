---
title: Charts
order: 5
---

# Charts

A chart takes rows, like the Table does. `x` names the category or time
column and `y` the value column, or several of them. Each series takes the
next of the theme's five chart colours, in the order given, and keeps it
when a neighbour disappears. Five series is the limit: a sixth has no colour
of its own, so fold it into another or draw a second chart. Every chart has
a tooltip; a legend appears from two series up.

## Bar chart

`ui.BarChart` compares magnitudes by category. `labels=True` writes the
value at the end of each bar; `format` chooses `number`, `integer`,
`percent` or `currency`.

```python live
MONTHS = [
    {"month": "Jan", "sales": 42, "costs": 31, "visits": 1200},
    {"month": "Feb", "sales": 48, "costs": 30, "visits": 1350},
    {"month": "Mar", "sales": 55, "costs": 34, "visits": 1600},
    {"month": "Apr", "sales": 51, "costs": 35, "visits": 1500},
    {"month": "May", "sales": 63, "costs": 38, "visits": 1900},
    {"month": "Jun", "sales": 70, "costs": 41, "visits": 2100},
]

ui.BarChart(MONTHS, x="month", y={"sales": "Sales", "costs": "Costs"}, labels=True, height=220)
```

## Stacked, percent and horizontal

`stacked=True` adds the series up; `stacked="percent"` draws every bar full
and shows each series' share. `horizontal=True` turns the chart on its side,
which suits long category names.

```python live
SHARE = [
    {"channel": "Direct", "new": 120, "returning": 340},
    {"channel": "Search engines", "new": 410, "returning": 190},
    {"channel": "Social media", "new": 230, "returning": 80},
    {"channel": "Newsletter", "new": 40, "returning": 260},
]

ui.Grid(
    ui.BarChart(SHARE, x="channel", y=["new", "returning"], stacked=True, height=200),
    ui.BarChart(
        SHARE, x="channel", y=["new", "returning"], stacked="percent", horizontal=True, height=200
    ),
    cols={"sm": 1, "md": 2},
)
```

## Long rows

Data often arrives with one row per series and category. `by` names the
column that holds the series name, and `y` the one column with the values;
Python pivots the rows before they leave.

```python live
REGIONS = [
    {"quarter": "Q1", "region": "North", "orders": 120},
    {"quarter": "Q1", "region": "South", "orders": 90},
    {"quarter": "Q2", "region": "North", "orders": 140},
    {"quarter": "Q2", "region": "South", "orders": 110},
    {"quarter": "Q3", "region": "North", "orders": 135},
    {"quarter": "Q3", "region": "South", "orders": 150},
]

ui.BarChart(REGIONS, x="quarter", y="orders", by="region", height=200)
```

## A diverging scale

When the series are steps of one ordered scale, `diverging=True` draws them
to either side of the midpoint, coloured from one hue through grey to
another instead of five unrelated colours. The middle step, when there is
one, straddles the axis.

```python live
WEATHER = [
    {"month": "Mar", "freezing": 4, "cold": 12, "mild": 10, "warm": 5, "hot": 0},
    {"month": "Apr", "freezing": 1, "cold": 8, "mild": 14, "warm": 7, "hot": 0},
    {"month": "May", "freezing": 0, "cold": 3, "mild": 12, "warm": 13, "hot": 3},
    {"month": "Jun", "freezing": 0, "cold": 1, "mild": 8, "warm": 15, "hot": 6},
]

ui.BarChart(
    WEATHER,
    x="month",
    y=["freezing", "cold", "mild", "warm", "hot"],
    diverging=True,
    horizontal=True,
    height=200,
)
```

## Emphasis

Often one series is the point and the rest are context. `emphasis` names
the one that keeps its colour; the others recede into grey.

```python live
ui.LineChart(
    MONTHS,
    x="month",
    y={"sales": "Sales", "costs": "Costs"},
    emphasis="sales",
    labels=True,
    height=200,
)
```

## Line and area

`ui.LineChart` draws a trend over an ordered x. `curve=True` smooths it,
`dots=True` marks the points, and `labels=True` names each line at its end
rather than numbering every point. `ui.AreaChart` fills under the line and
`stacked=True` adds the series up.

```python live
ui.Grid(
    ui.LineChart(MONTHS, x="month", y="visits", curve=True, dots=True, height=200),
    ui.AreaChart(
        MONTHS, x="month", y={"sales": "Sales", "costs": "Costs"}, stacked=True, height=200
    ),
    cols={"sm": 1, "md": 2},
)
```

## Clicks

`on_click` receives the point: its `x`, the `series` key and `value` for a
bar, and `values` for every series at that x. On a line or area chart the
click lands on the nearest x.

```python live
from pydantic import BaseModel


class Picked(BaseModel):
    text: str = "Click a bar."


def picked(s, point):
    state(Picked).text = f"{point['series']} in {point['x']}: {point['value']}"


def example(s):
    return ui.Stack(
        ui.BarChart(MONTHS, x="month", y=["sales", "costs"], on_click=picked, height=180),
        ui.Text(state(Picked).text, variant="muted"),
        gap=2,
    )
```

## Stat

`ui.Stat` is the headline number. `delta` is the change, drawn with its
direction; `good="down"` says a fall is the welcome move, for costs or
errors. `trend` draws a sparkline whose last point is the current one.

```python live
ui.Grid(
    ui.Stat(label="Revenue", value="€ 70k", delta=0.11, trend=[42, 48, 55, 51, 63, 70]),
    ui.Stat(label="Costs", value="€ 41k", delta=0.08, good="down", trend=[31, 30, 34, 35, 38, 41]),
    ui.Stat(label="Open tickets", value="12", delta=-3, delta_format="number", good="down"),
    cols={"sm": 1, "md": 3},
)
```

## Plotly and other libraries

The catalogue draws the forms most pages need. For anything else, an app
brings its own library through a custom component. Plotly is the common
case; the same shape works for any library that draws into a div.

The page may only run scripts from its own origin, so the library is served
by the app itself: put `plotly.min.js` in the app's `public/` folder. The
custom component loads it once, then hands the figure to Plotly whenever
the props change.

```jsx
// components/Plotly.jsx
import { useEffect, useRef } from "react";

let loading = null;

function loadPlotly() {
  if (window.Plotly) return Promise.resolve(window.Plotly);
  loading ??= new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `${window.__mw.base || ""}/public/plotly.min.js`;
    script.onload = () => resolve(window.Plotly);
    script.onerror = () => reject(new Error("plotly.min.js did not load"));
    document.head.appendChild(script);
  });
  return loading;
}

export default function Plotly({ props }) {
  const ref = useRef(null);
  useEffect(() => {
    let alive = true;
    loadPlotly().then((Plotly) => {
      if (!alive || !ref.current) return;
      const { data, layout } = props.figure;
      Plotly.react(ref.current, data, layout, { responsive: true, displaylogo: false });
    });
    return () => {
      alive = false;
    };
  }, [props.figure]);
  useEffect(() => () => window.Plotly?.purge(ref.current), []);
  return <div ref={ref} style={{ width: "100%", height: props.height ?? 320 }} />;
}
```

On the Python side a figure is built as usual and sent as JSON. A
transparent background lets the page's own colours through in both
schemes; the figure's own colours are Plotly's, not the theme's. Plotly
Express wants pandas installed next to it; graph objects need nothing.

```python
import json

import plotly.express as px

def example(s):
    fig = px.line(MONTHS, x="month", y="visits", markers=True)
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
    )
    return ui.Custom("Plotly", props={"figure": json.loads(fig.to_json()), "height": 300})
```

A click on a bar or a point can come back the same way as in the Hello
component: register a Plotly event on the div and call `emit`.

## Images from Python

Any library that renders to SVG or PNG works without a component at all:
the session keeps the bytes and `ui.Image` shows them. No tooltip, no theme
awareness, no script in the browser.

```python
import io

import matplotlib.pyplot as plt

def example(s):
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.plot([m["month"] for m in MONTHS], [m["visits"] for m in MONTHS])
    out = io.BytesIO()
    fig.savefig(out, format="svg", transparent=True)
    plt.close(fig)
    return ui.Image(src=s.files.add(out.getvalue(), name="visits.svg"), alt="Visits per month")
```
