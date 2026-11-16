"""Record this example's picture: three questions about the orders, and
one about a file that is attached to it. Run from the repository root:

    uv run python examples/analyst/record.py

It runs on the script, without a model, so the picture is the same each
time.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from recording import Recording, Window, picture, served  # noqa: E402

PORT = 8034
FIELD = "document.querySelector('textarea')"


def chip(text: str) -> str:
    """A suggestion under the chat, by what it says."""
    return f"[...document.querySelectorAll('button')].find(b => b.textContent.trim() === '{text}')"


async def record(base: str) -> None:
    desk = Window(1152, 752, scheme="dark")
    await desk.open()
    try:
        await desk.go(base + "/")
        film = Recording(desk)
        await film.rest(0.8)

        # 1. A question. The answer comes with the query it ran, and a chart
        # of it is pinned to the board.
        await film.click(desk, chip("Which region sold the most in 2025?"))
        await film.capture(3.4)
        await film.rest(0.8)

        # 2. A chart that is asked for.
        await film.click(desk, chip("Show revenue by month"))
        await film.capture(2.8)
        await film.rest(0.8)

        # 3. A question about the chart. The analyst points at it.
        await film.click(desk, chip("What happened in March 2026?"))
        await film.capture(5.0)
        await film.rest(1.0)
        await film.still()

        # 4. A file of the person's own, attached to a message, becomes a
        # table to ask about.
        await desk.attach(
            "document.querySelector('input[type=file]')", HERE / "samples" / "returns.csv"
        )
        await film.rest(1.0)
        await desk.eval(f"{FIELD}.focus()")
        await film.type(desk, "What is in this?")
        await film.enter(desk)
        await film.capture(3.0)
        await film.rest(2.2)
    finally:
        await desk.close()
    out = HERE / "analyst.gif"
    picture(out, [(desk, 23, 23, 1152)], backdrop="0x05070a")
    print(f"{len(desk.frames)} frames, {out.name} {out.stat().st_size / 1e6:.2f} MB")


async def main() -> None:
    async with served(HERE / "app.py", PORT) as base:
        await record(base)


if __name__ == "__main__":
    asyncio.run(main())
