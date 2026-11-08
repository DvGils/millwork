// Catalogue components backed by shadcn: a thin wrapper each, props in, events out.

import type { Renderer } from "../render";
import { Slot } from "../render";
import { cn } from "cn";
import { has } from "../lib";
import { icon } from "../icons";
import { t } from "../theme";
import { PasswordInput, useDebounced, useOwned } from "./inputs";
import { Button as UiButton, buttonVariants } from "@/components/ui/button";
import { anchorProps } from "./anchor";
import { Input as UiInput } from "@/components/ui/input";
import {
  Card as UiCard,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge as UiBadge } from "@/components/ui/badge";
import { Separator as UiSeparator } from "@/components/ui/separator";
import { Spinner } from "@/components/ui/spinner";

const buttonVariant: Record<string, "default" | "secondary" | "outline" | "ghost" | "link" | "destructive"> = {
  primary: "default",
  secondary: "secondary",
  outline: "outline",
  ghost: "ghost",
  link: "link",
  destructive: "destructive",
};

const buttonSize: Record<string, "sm" | "default" | "lg"> = { sm: "sm", md: "default", lg: "lg" };

export const Button: Renderer = ({ props, emit }) => {
  const Icon = icon(props.icon);
  const label = String(props.label ?? "");
  // `confirm` is the server's business: the session asks before running the handler.
  const click = () => {
    if (props.on_click) emit("click");
  };
  const inner = (
    <>
      {props.loading ? <Spinner /> : Icon && props.icon_position !== "end" ? <Icon /> : null}
      {label}
      {!props.loading && Icon && props.icon_position === "end" ? <Icon /> : null}
    </>
  );
  // With an href the button is a link that looks like one: the browser can
  // open it in a new tab, copy it and show where it goes. A disabled one goes
  // nowhere, so it stays a button.
  if (props.href && !props.disabled && !props.loading) {
    return (
      <a
        {...anchorProps(props.href, props.target)}
        data-slot="button"
        title={props.tooltip ? String(props.tooltip) : undefined}
        // Merged like the button's own classes: a variant overrides the base.
        className={cn(
          buttonVariants({
            variant: buttonVariant[String(props.variant ?? "primary")],
            size: buttonSize[String(props.size ?? "md")],
            className: props.cls as string,
          }),
        )}
      >
        {inner}
      </a>
    );
  }
  return (
    <UiButton
      variant={buttonVariant[String(props.variant ?? "primary")]}
      size={buttonSize[String(props.size ?? "md")]}
      disabled={Boolean(props.disabled) || Boolean(props.loading)}
      title={props.tooltip ? String(props.tooltip) : undefined}
      onClick={props.on_click ? click : undefined}
      className={props.cls as string}
      type={props.form ? "submit" : "button"}
      form={props.form ? `mw-form-${String(props.form)}` : undefined}
    >
      {inner}
    </UiButton>
  );
};

// Input: on the wire `value` means server-owned (shown as is); `default` keeps a draft here.
export const Input: Renderer = ({ props, emit }) => {
  const controlled = has(props, "value");
  const [current, setDraft] = useOwned<string>(controlled, String(props.value ?? ""), String(props.default ?? ""));
  const later = useDebounced(typeof props.debounce_ms === "number" ? props.debounce_ms : 250);
  const Prefix = icon(props.prefix_icon);
  const Clear = icon("x");
  const secret = props.kind === "password";
  const Field = secret ? PasswordInput : UiInput;
  // A password is wrapped as well: its eye sits at the field's end, and the
  // app's classes go on the box around both.
  const wrapped = Boolean(Prefix || props.suffix || props.clearable || secret);
  const clearable = Boolean(props.clearable) && current !== "" && !props.disabled && !props.readonly;
  const clear = () => {
    setDraft("");
    if (props.on_change) emit("change", "");
  };
  const field = (
    <Field
      type={secret ? undefined : String(props.kind ?? "text")}
      value={current}
      placeholder={props.placeholder ? String(props.placeholder) : undefined}
      maxLength={typeof props.max_length === "number" ? props.max_length : undefined}
      disabled={Boolean(props.disabled)}
      readOnly={Boolean(props.readonly)}
      onChange={(e) => {
        const next = e.target.value;
        setDraft(next);
        if (props.on_change) later(() => emit("change", next));
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" && props.on_submit) {
          later.flush();
          emit("submit", current);
        }
      }}
      className={cn(Prefix && "pl-8", props.clearable && (secret ? "pr-14" : "pr-8"), !wrapped && (props.cls as string))}
    />
  );
  if (!wrapped) return field;
  // The clear button sits left of the suffix and of a password's eye.
  const clearAt = props.suffix ? (secret ? "right-20" : "right-14") : secret ? "right-8" : "right-2";
  // The app's classes (a margin, a width) go on the outer box, so the icon and
  // the clear button stay centred on the input itself.
  return (
    <div className={cn("relative flex items-center gap-2", props.cls as string)}>
      {Prefix ? <Prefix className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" /> : null}
      {field}
      {clearable && Clear ? (
        <button
          type="button"
          aria-label={t("clear")}
          onClick={clear}
          className={cn("absolute top-1/2 -translate-y-1/2 rounded-sm text-muted-foreground hover:text-foreground", clearAt)}
        >
          <Clear className="size-4" />
        </button>
      ) : null}
      {props.suffix ? <span className="text-sm text-muted-foreground">{String(props.suffix)}</span> : null}
    </div>
  );
};

const cardTone: Record<string, string> = {
  muted: "bg-muted/40",
  primary: "border-primary/40",
  accent: "bg-accent",
  success: "border-success/40",
  warning: "border-warning/40",
  destructive: "border-destructive/40",
};

export const Card: Renderer = ({ props, children, emit }) => (
  <UiCard
    className={cn(props.tone ? cardTone[String(props.tone)] : undefined, props.on_click && "cursor-pointer", props.cls as string)}
    onClick={props.on_click ? () => emit("click") : undefined}
  >
    {props.title || props.description ? (
      <CardHeader>
        {props.title ? <CardTitle>{String(props.title)}</CardTitle> : null}
        {props.description ? <CardDescription>{String(props.description)}</CardDescription> : null}
      </CardHeader>
    ) : null}
    {/* The content takes the height a taller neighbor gives the card, so the
        footer sits at the bottom of every card in a row. */}
    <CardContent className={cn("flex grow flex-col gap-4", props.padding === false && "p-0")}>{children}</CardContent>
    {props.footer ? (
      <CardFooter>
        <Slot value={props.footer} />
      </CardFooter>
    ) : null}
  </UiCard>
);

const badgeVariant: Record<string, "default" | "secondary" | "outline" | "destructive"> = {
  default: "default",
  muted: "secondary",
  primary: "default",
  accent: "secondary",
  success: "outline",
  warning: "outline",
  destructive: "destructive",
};

const badgeTone: Record<string, string> = {
  success: "border-success text-success",
  warning: "border-warning text-warning",
};

export const Badge: Renderer = ({ props }) => {
  const Icon = icon(props.icon);
  return (
    <UiBadge variant={badgeVariant[String(props.tone ?? "default")]} className={cn(badgeTone[String(props.tone)], props.cls as string)}>
      {Icon ? <Icon /> : null}
      {String(props.label ?? "")}
    </UiBadge>
  );
};

export const Separator: Renderer = ({ props }) => {
  if (props.label) {
    return (
      <div className={cn("flex items-center gap-3 text-xs text-muted-foreground", props.cls as string)}>
        <UiSeparator className="flex-1" />
        {String(props.label)}
        <UiSeparator className="flex-1" />
      </div>
    );
  }
  return <UiSeparator orientation={props.orientation === "vertical" ? "vertical" : "horizontal"} className={props.cls as string} />;
};
