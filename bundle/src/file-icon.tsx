// An icon of the app's own: a file under public/, drawn in the place and at
// the size of one of the bundle's icons.
//
// The file is never put into the page as markup. It is an image inside an
// <svg> of ours, so whatever it holds beyond what it looks like is not run.
// An SVG file is the mask of a square in the text's color: only its shape
// counts, and it follows the color around it the way the bundle's icons
// do. Any other image is drawn as it is. Either way the element is a real
// <svg> with the icon inside its view box, which is what the rules that
// size, space, pad and frame icons work on.

import { useId, useState, type ComponentType } from "react";
import { toBrowser } from "./lib";

export type IconType = ComponentType<{ className?: string }>;

// The one shape a path may have, the same as the server checks: under
// public/ as it is spelled, no segment that starts with a dot, and a kind
// of image at the end, in either case. A path of this shape holds nothing
// that could end the attribute it is written into.
const FILE = /^\/public(?:\/[A-Za-z0-9_-][A-Za-z0-9._-]*)+\.([A-Za-z]+)$/;
const KINDS = new Set(["svg", "png", "webp", "jpg", "jpeg"]);
const LIMIT = 200;

const told = new Set<string>();

// A file that is not there, said once, so a typo is found in the console.
function missing(path: string) {
  if (told.has(path)) return;
  told.add(path);
  console.warn(`millwork: no icon at "${path}"`);
}

function FileIcon({ path, tinted, className }: { path: string; tinted: boolean; className?: string }) {
  // The mask is found by its id, which only has to be this icon's own.
  const id = `mw-icon-${useId().replace(/[^A-Za-z0-9]/g, "")}`;
  // A file that did not load draws nothing, where the browser would draw
  // its sign for a broken image.
  const [gone, setGone] = useState(false);
  const image = (
    <image
      href={toBrowser(path)}
      width="24"
      height="24"
      onError={() => {
        missing(path);
        setGone(true);
      }}
    />
  );
  return (
    <svg data-slot="file-icon" aria-hidden="true" width="24" height="24" viewBox="0 0 24 24" className={className}>
      {gone ? null : tinted ? (
        <>
          <mask id={id} style={{ maskType: "alpha" }}>
            {image}
          </mask>
          <rect width="24" height="24" fill="currentColor" mask={`url(#${id})`} />
        </>
      ) : (
        image
      )}
    </svg>
  );
}

const drawn = new Map<string, IconType>();

export function fileIcon(path: string): IconType | null {
  const known = drawn.get(path);
  if (known) return known;
  const shape = path.length <= LIMIT ? FILE.exec(path) : null;
  const kind = shape ? shape[1].toLowerCase() : "";
  if (!KINDS.has(kind)) return null;
  const tinted = kind === "svg";
  // One component per path, so drawing it again is the same element and
  // not a new one each time.
  const icon: IconType = ({ className }) => <FileIcon path={path} tinted={tinted} className={className} />;
  drawn.set(path, icon);
  return icon;
}
