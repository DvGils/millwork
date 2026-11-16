"""Record this example's picture: a cell that is followed, seen close
and then in the dark field. Run from
the repository root:

    uv run python examples/microscope/record.py

The drop is another one every time, so no two pictures are the same.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import recording  # noqa: E402
from recording import Recording, Window, picture, served  # noqa: E402

# A drop is watched at its own pace, where a page that is used is shown
# a little faster than it was.
recording.SPEED = 1.0

PORT = 8035
CANVAS = "document.querySelector('canvas')"


def button(group: str, text: str) -> str:
    """A button of one of the microscope's controls, by what it says."""
    inside = f"document.querySelector('[data-node$=\"/{group}\"]')"
    return f"[...{inside}.querySelectorAll('button')].find(b => b.textContent.trim() === '{text}')"


def said(text: str) -> str:
    return f"[...document.querySelectorAll('button')].find(b => b.textContent.trim() === '{text}')"


async def follow_a_grazer(desk: Window) -> None:
    """Press around the view until a grazer is followed, as a person
    presses the one they want. It is done before the picture starts."""
    box = json.loads(
        await desk.eval(
            f"(b => JSON.stringify([b.left, b.top, b.width]))({CANVAS}.getBoundingClientRect())"
        )
    )
    left, top, width = box
    for n in range(200):
        x = left + width * (0.3 + 0.4 * ((n * 7) % 11) / 11)
        y = top + width * (0.3 + 0.4 * ((n * 3) % 11) / 11)
        for kind in ("mousePressed", "mouseReleased"):
            await desk.call(
                "Input.dispatchMouseEvent", type=kind, x=x, y=y, button="left", clickCount=1
            )
        await asyncio.sleep(0.2)
        if await desk.eval("document.body.innerText.includes('A grazer of the')"):
            return
        if await desk.eval("document.body.innerText.includes('Let it go')"):
            await desk.eval(f"{said('Let it go')}.click()")
    raise RuntimeError("no grazer came under the pointer")


async def record(base: str) -> None:
    desk = Window(1152, 800)
    await desk.open()
    try:
        await desk.go(base + "/")
        # Some generations first, so that the drop has a history to show.
        await desk.eval(f"{button('pace', '4×')}.click()")
        await asyncio.sleep(10)
        await desk.eval(f"{button('pace', '1×')}.click()")
        await follow_a_grazer(desk)
        film = Recording(desk)
        await film.rest(3.0)
        await film.still()

        # 1. The strongest objective, on the cell that is followed.
        await film.click(desk, button("objective", "40×"))
        await film.rest(5.0)

        # 2. The dark field, in which the cells light up.
        await film.click(desk, button("field", "Dark"))
        await film.rest(4.5)

        # 3. And back out, to more of the drop.
        await film.click(desk, button("objective", "10×"))
        await film.rest(4.0)
    finally:
        await desk.close()
    out = HERE / "microscope.webp"
    picture(out, [(desk, 23, -1, 1152)])
    print(f"{len(desk.frames)} frames, {out.name} {out.stat().st_size / 1e6:.2f} MB")


async def main() -> None:
    async with served(HERE / "app.py", PORT) as base:
        await record(base)


if __name__ == "__main__":
    asyncio.run(main())
