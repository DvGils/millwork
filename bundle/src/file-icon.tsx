// An icon of the app's own: a file under public/, drawn in the place and at
// the size of one of the bundle's icons.
//
// The file is never put into the page as markup. An SVG is the shape of a
// mask over the text's color, so it follows the color around it the way
// the bundle's icons do, and whatever a file holds beyond its shape is
// not run. Any other image is drawn as it is. Either way the element is an
// <svg>, which is what the rules that size and space icons look for.

import type { ComponentType, CSSProperties } from "react";
import { cn } from "cn";
import { toBrowser } from "./lib";

export type IconType = ComponentType<{ className?: string }>;

// The one shape a path may have, the same as the server checks: under
// public/, no segment that starts with a dot, and a kind of image at the
// end. A path of this shape holds nothing that could end the url() it is
// written into.
const FILE = /^\/public(?:\/[A-Za-z0-9_-][A-Za-z0-9._-]*)+\.(svg|png|webp|jpe?g)$/i;
const LIMIT = 200;

const drawn = new Map<string, IconType>();

export function fileIcon(path: string): IconType | null {
  const known = drawn.get(path);
  if (known) return known;
  const shape = path.length <= LIMIT ? FILE.exec(path) : null;
  if (!shape) return null;
  const url = toBrowser(path);
  // A mask that is not there draws nothing and says nothing, so the file is
  // asked for once here, to say so when it is missing.
  if (typeof Image !== "undefined") {
    const probe = new Image();
    probe.onerror = () => console.warn(`millwork: no icon at "${path}"`);
    probe.src = url;
  }
  const icon: IconType =
    shape[1].toLowerCase() === "svg"
      ? ({ className }) => (
          <svg
            data-slot="file-icon"
            aria-hidden="true"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            className={cn("mw-file-icon", className)}
            style={{ "--mw-icon": `url("${url}")` } as CSSProperties}
          />
        )
      : ({ className }) => (
          <svg data-slot="file-icon" aria-hidden="true" width="24" height="24" viewBox="0 0 24 24" className={className}>
            <image href={url} width="24" height="24" />
          </svg>
        );
  // One component per path, so drawing it again is the same element and
  // not a new one each time.
  drawn.set(path, icon);
  return icon;
}
