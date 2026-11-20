// A color as the picker holds it and as the page does. The page has a hex
// code, `#rrggbb`. The picker has a hue from 0 up to 360 with a saturation and
// a brightness from 0 to 1, which is where the square and the strip point.

export interface Hsv {
  h: number;
  s: number;
  v: number;
}

const HEX = /^#[0-9a-f]{6}$/;
const SHORT = /^#[0-9a-f]{3}$/;

// What was typed as a hex code, or null when it is none. The `#` may be left
// out and the letters may be capitals. Three digits count only where the
// caller takes them, as they are also the start of six.
export function parseHex(typed: string, short = false): string | null {
  const text = typed.trim().toLowerCase();
  const code = text.startsWith("#") ? text : `#${text}`;
  if (HEX.test(code)) return code;
  if (short && SHORT.test(code)) return `#${code[1]}${code[1]}${code[2]}${code[2]}${code[3]}${code[3]}`;
  return null;
}

export function toHex({ h, s, v }: Hsv): string {
  const part = (n: number) => {
    const k = (n + h / 60) % 6;
    const x = v - v * s * Math.max(0, Math.min(k, 4 - k, 1));
    return Math.round(x * 255)
      .toString(16)
      .padStart(2, "0");
  };
  return `#${part(5)}${part(3)}${part(1)}`;
}

// The color as the picker holds it. A gray has no hue and black has no
// saturation either, so those are kept from `was`, where the person left
// the square and the strip.
export function toHsv(hex: string, was?: Hsv): Hsv {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b);
  const spread = max - Math.min(r, g, b);
  if (max === 0) return { h: was?.h ?? 0, s: was?.s ?? 0, v: 0 };
  if (spread === 0) return { h: was?.h ?? 0, s: 0, v: max };
  let h = max === r ? ((g - b) / spread) % 6 : max === g ? (b - r) / spread + 2 : (r - g) / spread + 4;
  h = (h * 60 + 360) % 360;
  return { h, s: spread / max, v: max };
}

// Where the square and the strip are for a color the page gave. They stay
// where the person left them when that is the same color: many places in the
// square are one hex code, and the hue of a gray is nowhere in it.
export function placed(hex: string | null, was: Hsv): Hsv {
  if (hex === null || toHex(was) === hex) return was;
  return toHsv(hex, was);
}
