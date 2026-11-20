// The ColorPicker: a swatch that opens a square for saturation and brightness,
// a strip for the hue, the hex code and the page's own colors. What is dragged
// shows at once and reaches the page when it is let go.

import { type CSSProperties, type KeyboardEvent, type PointerEvent, useEffect, useRef, useState } from "react";
import type { Renderer } from "../render";
import { cn } from "cn";
import { has } from "../lib";
import { icon } from "../icons";
import { t } from "../theme";
import { type Hsv, parseHex, placed, toHex } from "../color";
import { ANSWERED_WITHIN } from "../owned";
import { useOwned } from "./inputs";
import { Button as UiButton } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

const clamp = (n: number) => Math.min(1, Math.max(0, n));
// Where the square and the strip start for a field with no color yet.
const START: Hsv = { h: 0, s: 0, v: 1 };
const ARROWS: Record<string, [number, number]> = {
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
  ArrowUp: [0, 1],
  ArrowDown: [0, -1],
};

// What makes an element a place to point at: a press or a drag gives where in
// it, each from 0 to 1, and an arrow key a step, larger with shift. `done`
// runs when the pointer or the key is let go.
function pointed(point: (x: number, y: number) => void, step: (dx: number, dy: number) => void, done: () => void) {
  const at = (e: PointerEvent<HTMLElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    point(clamp((e.clientX - box.left) / box.width), clamp((e.clientY - box.top) / box.height));
  };
  return {
    onPointerDown: (e: PointerEvent<HTMLElement>) => {
      if (e.button !== 0) return;
      // The element keeps the pointer, so a drag goes on outside it. Without
      // the browser's own part of a press, nothing is selected and the
      // keyboard has to be sent here.
      e.preventDefault();
      e.currentTarget.setPointerCapture(e.pointerId);
      e.currentTarget.focus();
      at(e);
    },
    onPointerMove: (e: PointerEvent<HTMLElement>) => {
      if (e.currentTarget.hasPointerCapture(e.pointerId)) at(e);
    },
    onLostPointerCapture: done,
    onKeyDown: (e: KeyboardEvent<HTMLElement>) => {
      const by = ARROWS[e.key];
      if (!by) return;
      e.preventDefault();
      const size = e.shiftKey ? 0.1 : 0.01;
      step(by[0] * size, by[1] * size);
    },
    onKeyUp: (e: KeyboardEvent<HTMLElement>) => {
      if (ARROWS[e.key]) done();
    },
    onBlur: done,
  };
}

// A color that was let go of and that the page does not have yet: where it
// was left, the page's color when the wait began, and each code told since.
interface Left {
  at: Hsv;
  from: string | null;
  told: string[];
}

function Chip({ color, className }: { color: string | null; className?: string }) {
  return <span className={cn("mw-color-chip", color === null && "mw-color-none", className)} style={color ? { background: color } : undefined} />;
}

export function ColorPickerControl({
  value: given,
  onChange,
  swatches: offered,
  compact,
  label,
  placeholder,
  clearable,
  disabled,
  invalid,
  waits,
  id,
}: {
  value: string | null;
  onChange: (next: string | null) => void;
  // Whether `value` follows a pick only once the page has answered it.
  waits?: boolean;
  swatches?: string[];
  compact?: boolean;
  label?: string;
  placeholder?: string;
  clearable?: boolean;
  disabled?: boolean;
  invalid?: boolean;
  id?: string;
}) {
  const [open, setOpen] = useState(false);
  // A form holds whatever its document does, so what is no hex code is no
  // color here, and is not drawn or worked out with.
  const value = given === null ? null : parseHex(given, true);
  const swatches = [...new Set((offered ?? []).map((color) => parseHex(String(color), true)).filter((color) => color !== null))];
  // Where the square and the strip are while they are moved.
  const [held, setHeld] = useState<Hsv | null>(null);
  const holding = useRef<Hsv | null>(null);
  // Where they were let go, for as long as the page's answer is on its way.
  // The page's color is then still the one from before, or one let go of
  // earlier. Any other color is the page's own answer, and is shown.
  const [left, setLeft] = useState<Left | null>(null);
  const arrived = left !== null && value === toHex(left.at);
  const due = left !== null && !arrived && (value === left.from || (value !== null && left.told.includes(value)));
  // Where they are at rest, which is the page's color.
  const rest = useRef<Hsv>(START);
  if (arrived) rest.current = left.at;
  rest.current = placed(value, rest.current);
  // What is being typed as a hex code, while it is.
  const [typed, setTyped] = useState<string | null>(null);

  const settled = due ? left.at : rest.current;
  const at = held ?? settled;
  const hex = held ? toHex(held) : due ? toHex(left.at) : value;
  const pure = toHex({ h: at.h, s: 1, v: 1 });

  // An answer that came, or one that is not coming, ends the wait.
  const over = left !== null && !due;
  useEffect(() => {
    if (over) setLeft(null);
  }, [over]);
  useEffect(() => {
    if (!left) return;
    const timer = window.setTimeout(() => setLeft(null), ANSWERED_WITHIN);
    return () => window.clearTimeout(timer);
  }, [left]);

  const move = (next: Hsv) => {
    holding.current = next;
    setHeld(next);
    setTyped(null);
  };
  const drop = () => {
    holding.current = null;
    setHeld(null);
  };
  const letGo = () => {
    const moved = holding.current;
    if (!moved) return;
    drop();
    const code = toHex(moved);
    if (code === value) {
      rest.current = moved;
      return;
    }
    if (waits) setLeft((was) => ({ at: moved, from: was ? was.from : value, told: [...(was?.told ?? []), code] }));
    else rest.current = moved;
    onChange(code);
  };
  const now = () => holding.current ?? settled;

  const square = pointed(
    (x, y) => move({ ...now(), s: x, v: 1 - y }),
    (dx, dy) => move({ ...now(), s: clamp(now().s + dx), v: clamp(now().v + dy) }),
    letGo,
  );
  // A hue of 360 is the red of 0 again, so the strip stops just short of it.
  const strip = pointed(
    (x) => move({ ...now(), h: Math.min(359.9, x * 360) }),
    (dx, dy) => move({ ...now(), h: Math.min(359.9, clamp(now().h / 360 + dx + dy) * 360) }),
    letGo,
  );

  // Six digits are a color as soon as they are typed. Three are one when the
  // field is left, as they are also how six begin.
  const type = (text: string) => {
    setTyped(text);
    const code = parseHex(text);
    if (code && code !== value) onChange(code);
  };
  const typedOut = () => {
    if (typed === null) return;
    const code = parseHex(typed, true);
    setTyped(null);
    if (code && code !== value) onChange(code);
  };
  const pick = (color: string | null) => {
    setTyped(null);
    if (color !== value) onChange(color);
    setOpen(false);
  };

  const Down = icon("chevron-down");
  const Clear = icon("x");
  const said = hex ? hex.toUpperCase() : t("no_color");
  const name = label ?? (compact ? t("color") : undefined);
  return (
    <Popover
      open={open}
      onOpenChange={(next, details) => {
        setOpen(next);
        if (next) return;
        // What is closed mid-drag has nothing left to say it was let go.
        // Escape takes the drag back, and any other way out keeps it.
        if (details.reason === "escape-key") drop();
        else letGo();
        setTyped(null);
      }}
    >
      <PopoverTrigger
        render={
          <UiButton
            id={id}
            type="button"
            variant="outline"
            size={compact ? "icon" : "default"}
            disabled={disabled}
            aria-invalid={invalid || undefined}
            aria-label={name ? `${name}, ${said}` : undefined}
            className={cn(!compact && "justify-start gap-2 px-2 font-normal", !compact && !hex && "text-muted-foreground")}
          />
        }
      >
        <Chip color={hex} />
        {compact ? null : <span className={cn(hex && "font-mono text-[0.8rem] tracking-wide")}>{hex ? hex.toUpperCase() : (placeholder ?? t("choose"))}</span>}
        {compact || !Down ? null : <Down className="ml-auto text-muted-foreground" />}
      </PopoverTrigger>
      <PopoverContent className="w-61 gap-3 p-3" align="start" aria-label={name ?? t("color")}>
        <div
          {...square}
          role="slider"
          tabIndex={0}
          aria-label={t("color_shade")}
          aria-valuenow={Math.round(at.s * 100)}
          aria-valuetext={t("color_shade_at", { s: Math.round(at.s * 100), v: Math.round(at.v * 100) })}
          className="mw-color-square"
          style={{ "--mw-hue": pure } as CSSProperties}
        >
          <span className="mw-color-thumb" style={{ left: `${at.s * 100}%`, top: `${(1 - at.v) * 100}%`, background: toHex(at) }} />
        </div>
        <div
          {...strip}
          role="slider"
          tabIndex={0}
          aria-label={t("hue")}
          aria-valuemin={0}
          aria-valuemax={360}
          aria-valuenow={Math.round(at.h)}
          aria-valuetext={`${Math.round(at.h)}°`}
          className="mw-color-strip"
        >
          <span className="mw-color-thumb" style={{ left: `${(at.h / 360) * 100}%`, background: pure }} />
        </div>
        <div className="flex items-center gap-2">
          <Chip color={hex} className="mw-color-chip-large" />
          <Input
            value={typed ?? (hex ? hex.toUpperCase() : "")}
            onChange={(e) => type(e.target.value)}
            onBlur={typedOut}
            onKeyDown={(e) => {
              if (e.key === "Enter") typedOut();
            }}
            aria-label={t("hex_code")}
            // Wrong is what can no longer become a code, not one half typed.
            aria-invalid={(typed !== null && !/^#?[0-9a-f]{0,6}$/i.test(typed.trim())) || undefined}
            placeholder="#000000"
            maxLength={7}
            spellCheck={false}
            autoComplete="off"
            className="h-8 min-w-0 font-mono text-[0.8rem] tracking-wide uppercase"
          />
          {clearable && value !== null && Clear ? (
            <UiButton type="button" variant="ghost" size="icon" className="shrink-0 text-muted-foreground" aria-label={t("no_color")} title={t("no_color")} onClick={() => pick(null)}>
              <Clear />
            </UiButton>
          ) : null}
        </div>
        {swatches.length ? (
          <div className="grid grid-cols-8 gap-1.5">
            {swatches.map((color) => (
              <button
                key={color}
                type="button"
                className="mw-color-swatch"
                style={{ background: color }}
                aria-label={color.toUpperCase()}
                title={color.toUpperCase()}
                aria-pressed={color === value}
                onClick={() => pick(color)}
              />
            ))}
          </div>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}

export const ColorPicker: Renderer = ({ props, emit }) => {
  const controlled = has(props, "value");
  const [current, setDraft] = useOwned<string | null>(controlled, (props.value as string | null) ?? null, (props.default as string | null) ?? null);
  return (
    <div className={props.cls as string}>
      <ColorPickerControl
        value={current}
        swatches={Array.isArray(props.swatches) ? (props.swatches as string[]) : undefined}
        compact={Boolean(props.compact)}
        label={props.label ? String(props.label) : undefined}
        placeholder={props.placeholder ? String(props.placeholder) : undefined}
        clearable={Boolean(props.clearable)}
        disabled={Boolean(props.disabled)}
        // A picker the page holds shows the page's color. A pick is its
        // color once the page says so, which is waited for when there is a
        // handler to say it.
        waits={controlled && Boolean(props.on_change)}
        onChange={(next) => {
          if (!controlled) setDraft(next);
          if (props.on_change) emit("change", next);
        }}
      />
    </div>
  );
};
