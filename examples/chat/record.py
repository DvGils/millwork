"""Record this example's picture: Ada at a desk and Sam on a phone, in the
same channel. Run from the repository root:

    uv run python examples/chat/record.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from recording import Recording, Window, gif, served  # noqa: E402

PORT = 8032
FIELD = "document.querySelector('input[placeholder^=\"Message\"]')"
# The button at a message's end that opens the reactions, and one of them.
REACT = "[data-slot=scroll-area-viewport] button[aria-haspopup]"
ITEM = (
    "[...document.querySelectorAll('[role=menuitem]')].find(e => e.textContent.includes('Agree'))"
)


def link(channel: str) -> str:
    return f"document.querySelector('[data-slot=sidebar] a[href=\"/c/{channel}\"]')"


async def join(window: Window, base: str, name: str) -> None:
    await window.go(base + "/")
    await window.eval("document.querySelector('input').focus()")
    for ch in name:
        await window.call("Input.insertText", text=ch)
    button = "[...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Join')"
    await window.eval(f"{button}.click()")
    await asyncio.sleep(1.0)


async def record(base: str) -> None:
    # Each on a clock of their own: the same messages, at the time it was
    # for the one who reads them.
    ada = Window(860, 740, zone="Europe/London")
    sam = Window(390, 780, scheme="dark", zone="Europe/Athens", phone=True)
    await ada.open()
    await sam.open()
    try:
        await join(ada, base, "Ada Park")
        await join(sam, base, "Sam Okafor")
        await asyncio.sleep(1.5)
        film = Recording(ada, sam)
        await film.rest(1.0)

        # 1. Sam asks something from his phone. Ada sees him typing from
        # the first letter, and then what he wrote.
        await sam.eval(f"{FIELD}.focus()")
        await film.type(sam, "Has anyone seen the new empty states?")
        await film.rest(0.4)
        await film.enter(sam)
        await film.rest(1.0)

        # 2. Ada answers.
        await film.click(ada, FIELD)
        await film.type(ada, "They are up in #design. One line and one button.")
        await film.rest(0.3)
        await film.enter(ada)
        await film.rest(1.0)

        # 3. Ada goes to read #design. What Sam says meanwhile is counted
        # on the channel she left, with an @ for the one that names her.
        await film.click(ada, link("design"))
        await film.rest(0.8)
        await film.type(sam, "Found them. Much calmer.")
        await film.enter(sam)
        await film.rest(0.5)
        await film.type(sam, "@ada lunch at one?")
        await film.enter(sam)
        await film.rest(1.3)

        # 4. And back, to a line above what is new to her.
        await film.click(ada, link("general"))
        await film.rest(1.6)

        # 5. A reaction says it without a word, on both screens.
        await film.click(ada, f"[...document.querySelectorAll('{REACT}')].at(-1)")
        await film.rest(0.5)
        await film.click(ada, ITEM)
        await film.rest(2.5)
    finally:
        await sam.close()
        await ada.close()
    out = HERE / "chat.gif"
    # The screen at the left, the phone beside it at two thirds of its size.
    gif(out, [(ada, 24, 29, 860), (sam, 908, 134, 260)])
    print(f"{len(ada.frames)} frames, {out.name} {out.stat().st_size / 1e6:.2f} MB")


async def main() -> None:
    async with served(HERE / "app.py", PORT) as base:
        await record(base)


if __name__ == "__main__":
    asyncio.run(main())
