// What is seen through the microscope, drawn on a canvas.
//
// Python sends the cells in view a few times a second, and this draws
// them sixty times a second, each on its way from where it was to where
// it is now. Dragging moves the slide, the wheel changes the objective
// and a press on a cell follows it. Each of those is said to Python, which
// holds what the microscope is set to.
import { useEffect, useRef } from "react";

// A cell as it comes: these are the places in its row.
const ID = 0, KIND = 1, X = 2, Y = 3, Z = 4, HEADING = 5, R = 6, HUE = 7, SPEED = 8, GEN = 9, FULL = 10;
// How blurred something is that lies off the depth in focus, in pixels for
// the whole depth of the drop. A weak objective has everything sharp.
const BLUR = { 4: 0, 10: 22, 40: 90 };

const lerp = (a, b, t) => a + (b - a) * t;
// A number in 0..1 that is always the same for the same n.
const chance = (n) => {
  const x = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
};

// The color a cell is drawn in: its own, or what the stain makes of it.
function hueOf(row, stain, latest) {
  if (stain === "speed") return lerp(225, 0, Math.min(1, Math.max(0, (row[SPEED] - 60) / 100)));
  if (stain === "generation") return lerp(265, 30, latest ? row[GEN] / latest : 0);
  if (stain === "energy") return lerp(0, 130, row[FULL] / 100);
  return row[HUE];
}

function paint(ctx, bright, hue, alpha, kind) {
  const sat = kind ? 62 : 58;
  if (bright) {
    ctx.fillStyle = `hsla(${hue}, ${sat}%, ${kind ? 44 : 55}%, ${0.5 * alpha})`;
    ctx.strokeStyle = `hsla(${hue}, ${sat}%, 26%, ${0.85 * alpha})`;
  } else {
    ctx.fillStyle = `hsla(${hue}, 90%, 62%, ${0.2 * alpha})`;
    ctx.strokeStyle = `hsla(${hue}, 95%, 74%, ${0.95 * alpha})`;
  }
}

// Something out of focus: a soft disc, larger and fainter the further off.
function soft(ctx, x, y, r, blur, bright, hue, alpha) {
  const out = r + blur;
  const faint = alpha * Math.min(1, (r * r) / (out * out) + 0.12);
  const glow = ctx.createRadialGradient(x, y, Math.max(0, r - blur * 0.4), x, y, out);
  const tone = bright ? `${hue}, 50%, 42%` : `${hue}, 90%, 66%`;
  glow.addColorStop(0, `hsla(${tone}, ${0.4 * faint})`);
  glow.addColorStop(1, `hsla(${tone}, 0)`);
  ctx.fillStyle = glow;
  ctx.beginPath();
  ctx.arc(x, y, out, 0, Math.PI * 2);
  ctx.fill();
}

// A grazer: an oval that swims the way it points, with hairs that beat
// around it and what it has eaten inside.
function grazer(ctx, row, r, now, bright, hue, alpha) {
  const long = r * 1.35, wide = r * 0.86;
  paint(ctx, bright, hue, alpha, 0);
  ctx.lineWidth = Math.max(1, r * 0.09);
  if (r > 9) {
    ctx.beginPath();
    for (let i = 0; i < 26; i++) {
      const a = (i / 26) * Math.PI * 2;
      const beat = Math.sin(now / 70 + i * 1.7 + row[ID]) * 0.5;
      const x = Math.cos(a) * long, y = Math.sin(a) * wide;
      ctx.moveTo(x, y);
      ctx.lineTo(x + Math.cos(a + beat) * r * 0.3, y + Math.sin(a + beat) * r * 0.3);
    }
    ctx.globalAlpha = 0.6;
    ctx.stroke();
    ctx.globalAlpha = 1;
  }
  ctx.beginPath();
  ctx.ellipse(0, 0, long, wide, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  if (r < 6) return;
  // The nucleus, toward the back.
  ctx.fillStyle = bright ? `hsla(${hue}, 45%, 24%, ${0.5 * alpha})` : `hsla(${hue}, 80%, 80%, ${0.45 * alpha})`;
  ctx.beginPath();
  ctx.ellipse(-long * 0.28, 0, long * 0.26, wide * 0.42, 0.3, 0, Math.PI * 2);
  ctx.fill();
  // The algae it has eaten, more of them the fuller it is.
  ctx.fillStyle = bright ? `hsla(105, 55%, 34%, ${0.75 * alpha})` : `hsla(110, 90%, 62%, ${0.8 * alpha})`;
  for (let i = 0; i < Math.round(row[FULL] / 22); i++) {
    const a = chance(row[ID] * 7 + i) * Math.PI * 2, far = 0.2 + chance(row[ID] + i * 3) * 0.45;
    ctx.beginPath();
    ctx.arc(Math.cos(a) * long * far + long * 0.2, Math.sin(a) * wide * far, r * 0.13, 0, Math.PI * 2);
    ctx.fill();
  }
  // A bubble at the front that fills and empties.
  const pulse = 0.5 + 0.5 * Math.sin(now / 420 + row[ID]);
  ctx.strokeStyle = bright ? `hsla(${hue}, 40%, 30%, ${0.5 * alpha})` : `hsla(${hue}, 90%, 85%, ${0.6 * alpha})`;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(long * 0.62, 0, r * (0.1 + 0.12 * pulse), 0, Math.PI * 2);
  ctx.stroke();
}

// A hunter: a larger cell with no fixed shape, that flows as it goes.
function hunter(ctx, row, r, now, bright, hue, alpha) {
  paint(ctx, bright, hue, alpha, 1);
  ctx.lineWidth = Math.max(1.2, r * 0.07);
  ctx.beginPath();
  for (let i = 0; i <= 48; i++) {
    const a = (i / 48) * Math.PI * 2;
    const out = r * (1 + 0.15 * Math.sin(3 * a + now / 700 + row[ID]) + 0.09 * Math.sin(5 * a - now / 500 + row[ID] * 2) + 0.12 * Math.cos(a));
    if (i) ctx.lineTo(Math.cos(a) * out, Math.sin(a) * out);
    else ctx.moveTo(Math.cos(a) * out, Math.sin(a) * out);
  }
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  if (r < 8) return;
  ctx.fillStyle = bright ? `hsla(${hue}, 50%, 22%, ${0.55 * alpha})` : `hsla(${hue}, 90%, 80%, ${0.5 * alpha})`;
  ctx.beginPath();
  ctx.arc(-r * 0.2, r * 0.1, r * 0.3, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = bright ? `hsla(${hue}, 40%, 30%, ${0.35 * alpha})` : `hsla(${hue}, 80%, 75%, ${0.4 * alpha})`;
  for (let i = 0; i < 14; i++) {
    const a = chance(row[ID] * 5 + i) * Math.PI * 2 + now / 4000, far = chance(row[ID] * 11 + i) * 0.72;
    ctx.beginPath();
    ctx.arc(Math.cos(a) * r * far, Math.sin(a) * r * far, r * 0.05, 0, Math.PI * 2);
    ctx.fill();
  }
}

function draw(canvas, held, props, now) {
  const ctx = canvas.getContext("2d");
  const size = canvas.width, half = size / 2;
  const { view, drop } = props;
  const bright = view.field !== "dark";
  const cam = held.cam;
  const scale = half / cam.radius;
  const px = (x) => half + (x - cam.x) * scale, py = (y) => half + (y - cam.y) * scale;
  const blurOf = (z) => (Math.abs(z / 100 - view.focus) * BLUR[view.objective] * size) / 620;
  const lamp = 0.35 + 0.65 * view.lamp;

  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, size, size);
  ctx.save();
  ctx.beginPath();
  ctx.arc(half, half, half, 0, Math.PI * 2);
  ctx.clip();

  // The light that comes up through the slide.
  const light = ctx.createRadialGradient(half, half, 0, half, half, half);
  if (bright) {
    light.addColorStop(0, `hsl(46, 70%, ${lerp(62, 96, lamp)}%)`);
    light.addColorStop(1, `hsl(42, 55%, ${lerp(48, 86, lamp)}%)`);
  } else {
    light.addColorStop(0, `hsl(215, 45%, ${lerp(4, 11, lamp)}%)`);
    light.addColorStop(1, "hsl(220, 50%, 3%)");
  }
  ctx.fillStyle = light;
  ctx.fillRect(0, 0, size, size);

  // The edge of the drop, where the water ends.
  ctx.lineWidth = Math.max(2, 14 * scale);
  ctx.strokeStyle = bright ? "hsla(40, 35%, 30%, 0.28)" : "hsla(200, 80%, 80%, 0.3)";
  ctx.beginPath();
  ctx.arc(px(0), py(0), drop * scale, 0, Math.PI * 2);
  ctx.stroke();
  ctx.fillStyle = bright ? "hsla(40, 30%, 35%, 0.16)" : "hsla(220, 60%, 2%, 0.6)";
  ctx.beginPath();
  ctx.rect(0, 0, size, size);
  ctx.arc(px(0), py(0), drop * scale, 0, Math.PI * 2, true);
  ctx.fill();

  // Specks that float in the water, which stay where they are in the drop.
  for (let i = 0; i < 70; i++) {
    const a = chance(i) * Math.PI * 2, far = Math.sqrt(chance(i + 99)) * drop;
    const x = px(Math.cos(a) * far), y = py(Math.sin(a) * far);
    if (x < -40 || y < -40 || x > size + 40 || y > size + 40) continue;
    soft(ctx, x, y, (1.5 + chance(i + 7) * 3) * scale + 0.6, blurOf(chance(i + 31) * 100) + 1, bright, bright ? 38 : 210, 0.5);
  }

  // The algae.
  const algae = props.algae || [];
  for (let i = 0; i < algae.length; i++) {
    const a = algae[i];
    if (!a) continue;
    const x = px(a[0]), y = py(a[1]);
    if (x < -30 || y < -30 || x > size + 30 || y > size + 30) continue;
    const r = Math.max(1.1, 2.6 * scale), blur = blurOf(a[2]);
    if (blur > 1.2) {
      soft(ctx, x, y, r, blur, bright, 105, 0.9);
      continue;
    }
    ctx.fillStyle = bright ? "hsla(102, 52%, 36%, 0.82)" : "hsla(112, 95%, 62%, 0.9)";
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
    if (r > 5) {
      ctx.fillStyle = bright ? "hsla(95, 60%, 24%, 0.5)" : "hsla(120, 90%, 82%, 0.6)";
      ctx.beginPath();
      ctx.arc(x - r * 0.25, y - r * 0.2, r * 0.38, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // The cells, the most blurred first so that what is sharp lies on top.
  const part = Math.min(1, (now - held.at) / held.every);
  const shown = [];
  let latest = 1;
  for (const cell of held.cells.values()) {
    const fade = cell.gone ? 1 - (now - cell.gone) / 450 : Math.min(1, (now - cell.born) / 300);
    if (fade <= 0) continue;
    const row = cell.to;
    latest = Math.max(latest, row[GEN]);
    const turn = ((row[HEADING] - cell.from[HEADING] + 540) % 360) - 180;
    cell.x = lerp(cell.from[X], row[X], part) / 10;
    cell.y = lerp(cell.from[Y], row[Y], part) / 10;
    cell.heading = cell.from[HEADING] + turn * part;
    shown.push([cell, fade, blurOf(lerp(cell.from[Z], row[Z], part))]);
  }
  shown.sort((a, b) => b[2] - a[2]);
  for (const [cell, fade, blur] of shown) {
    const row = cell.to;
    const x = px(cell.x), y = py(cell.y), r = (row[R] / 10) * scale;
    if (x < -r * 3 || y < -r * 3 || x > size + r * 3 || y > size + r * 3) continue;
    const hue = hueOf(row, view.stain, latest);
    // A cell goes out of focus by degrees: the blur comes up as the cell
    // itself goes, so one that drifts a little in depth does not flicker
    // between the two.
    const lost = r < 2.2 ? 1 : Math.min(1, Math.max(0, (blur - 1) / 7));
    if (lost > 0) soft(ctx, x, y, Math.max(1.4, r), Math.max(0.6, blur), bright, hue, fade * lost);
    if (lost < 1) {
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate((cell.heading * Math.PI) / 180);
      if (!bright) {
        ctx.shadowColor = `hsla(${hue}, 95%, 65%, 0.7)`;
        ctx.shadowBlur = 10;
      }
      (row[KIND] ? hunter : grazer)(ctx, row, r, now, bright, hue, fade * (1 - lost));
      ctx.restore();
    }
    if (row[ID] === props.followed) {
      // A ring around the cell that is followed.
      const ring = Math.max(r * 1.9, 16);
      ctx.strokeStyle = bright ? "hsla(20, 15%, 12%, 0.75)" : "hsla(45, 90%, 85%, 0.9)";
      ctx.lineWidth = 1.5;
      ctx.setLineDash([ring * 0.5, ring * 0.3]);
      ctx.lineDashOffset = -now / 60;
      ctx.beginPath();
      ctx.arc(x, y, ring, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  // The dark at the edge of what a lens shows.
  const edge = ctx.createRadialGradient(half, half, half * 0.62, half, half, half);
  edge.addColorStop(0, "rgba(0, 0, 0, 0)");
  edge.addColorStop(0.86, bright ? "rgba(20, 12, 0, 0.16)" : "rgba(0, 0, 0, 0.35)");
  edge.addColorStop(1, bright ? "rgba(10, 6, 0, 0.72)" : "rgba(0, 0, 0, 0.95)");
  ctx.fillStyle = edge;
  ctx.fillRect(0, 0, size, size);

  // A bar that says how long a round length is at this objective.
  const length = { 4: 200, 10: 100, 40: 20 }[view.objective];
  const bar = length * (half / view.radius), ink = bright ? "rgba(30, 22, 10, 0.8)" : "rgba(240, 235, 220, 0.85)";
  ctx.fillStyle = ink;
  ctx.fillRect(half - bar / 2, size * 0.86, bar, Math.max(2, size / 310));
  ctx.font = `500 ${Math.round(size / 44)}px ui-sans-serif, system-ui, sans-serif`;
  ctx.textAlign = "center";
  ctx.fillText(`${length} µm`, half, size * 0.86 - size / 90);
  ctx.restore();
}

export default function Scope({ props, emit }) {
  const canvas = useRef(null);
  // The props as they are now, for the loop that draws, which is started once.
  const given = useRef(props);
  given.current = props;
  const held = useRef({ cells: new Map(), at: 0, every: 200, cam: null, drag: null, said: 0, wheel: 0, turned: 0 }).current;
  if (!held.cam) held.cam = { x: props.view.x, y: props.view.y, radius: props.view.radius, tx: props.view.x, ty: props.view.y };

  // New cells from Python: each goes on from where it is drawn now.
  useEffect(() => {
    const t = performance.now();
    const seen = new Set();
    for (const row of props.cells || []) {
      seen.add(row[ID]);
      const cell = held.cells.get(row[ID]);
      if (cell) {
        cell.from = [...cell.to];
        cell.from[X] = cell.x * 10;
        cell.from[Y] = cell.y * 10;
        cell.from[HEADING] = cell.heading;
        cell.to = row;
        cell.gone = 0;
      } else {
        held.cells.set(row[ID], { from: row, to: row, x: row[X] / 10, y: row[Y] / 10, heading: row[HEADING], born: t, gone: 0 });
      }
    }
    for (const [id, cell] of held.cells) {
      if (seen.has(id)) continue;
      if (!cell.gone) cell.gone = t;
      else if (t - cell.gone > 450) held.cells.delete(id);
    }
    held.at = t;
    held.every = Math.max(60, (props.every || 0.2) * 1000);
  }, [props.cells]);

  // Where Python says the slide is, unless a drag is under way.
  useEffect(() => {
    if (!held.drag) {
      held.cam.tx = props.view.x;
      held.cam.ty = props.view.y;
    }
  }, [props.view.x, props.view.y]);

  useEffect(() => {
    const el = canvas.current;
    let frame = 0, last = performance.now();
    const fit = () => {
      const side = Math.round(el.clientWidth * Math.min(2, window.devicePixelRatio || 1));
      if (side && el.width !== side) el.width = el.height = side;
    };
    const tick = (t) => {
      fit();
      const cam = held.cam, ease = 1 - Math.exp(-(t - last) / 110);
      last = t;
      cam.x += (cam.tx - cam.x) * (held.drag ? 1 : ease);
      cam.y += (cam.ty - cam.y) * (held.drag ? 1 : ease);
      cam.radius += (given.current.view.radius - cam.radius) * ease;
      if (el.width) draw(el, held, given.current, t);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);

    // A place on the canvas as a place in the drop.
    const place = (e) => {
      const box = el.getBoundingClientRect(), per = held.cam.radius / (box.width / 2);
      return { x: held.cam.x + (e.clientX - box.left - box.width / 2) * per, y: held.cam.y + (e.clientY - box.top - box.height / 2) * per, per };
    };
    const down = (e) => {
      // One finger moves the slide. A second one is not a second slide.
      if (!e.isPrimary) return;
      el.setPointerCapture(e.pointerId);
      held.drag = { x: e.clientX, y: e.clientY, moved: false };
    };
    const move = (e) => {
      const drag = held.drag;
      if (!drag) return;
      if (!drag.moved && Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 5) return;
      const per = place(e).per, cam = held.cam;
      cam.tx -= (e.clientX - drag.x) * per;
      cam.ty -= (e.clientY - drag.y) * per;
      // The slide stops where the drop ends, as it does in Python.
      const out = Math.hypot(cam.tx, cam.ty) / given.current.drop;
      if (out > 1) {
        cam.tx /= out;
        cam.ty /= out;
      }
      Object.assign(drag, { x: e.clientX, y: e.clientY, moved: true });
      // Said to Python a few times a second, since the lamp goes with it.
      if (performance.now() - held.said > 120) {
        held.said = performance.now();
        emit("pan", { x: cam.tx, y: cam.ty });
      }
    };
    const up = (e) => {
      const drag = held.drag;
      held.drag = null;
      if (!drag) return;
      if (drag.moved) emit("pan", { x: held.cam.tx, y: held.cam.ty });
      else if (e.type === "pointerup") emit("pick", { x: place(e).x, y: place(e).y });
    };
    const wheel = (e) => {
      e.preventDefault();
      held.wheel += e.deltaY;
      if (Math.abs(held.wheel) < 60 || performance.now() - held.turned < 350) return;
      emit("zoom", held.wheel < 0 ? 1 : -1);
      held.wheel = 0;
      held.turned = performance.now();
    };
    el.addEventListener("pointerdown", down);
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
    el.addEventListener("wheel", wheel, { passive: false });
    return () => {
      cancelAnimationFrame(frame);
      el.removeEventListener("pointerdown", down);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
      el.removeEventListener("wheel", wheel);
    };
  }, []);

  return (
    <div className="mx-auto w-full max-w-[620px] p-4">
      {/* The tube of the microscope around what it shows. */}
      <div className="rounded-full bg-[#141210] p-[10px] shadow-[0_0_0_2px_#3b362f,0_22px_44px_-12px_rgba(20,14,4,0.55)]">
        <canvas
          ref={canvas}
          aria-label="The drop, as the microscope shows it"
          className="block aspect-square w-full cursor-grab touch-none rounded-full active:cursor-grabbing"
        />
      </div>
    </div>
  );
}
