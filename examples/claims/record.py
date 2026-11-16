"""Record this example's picture: Priya reviewing at a desk, and Nora
filing a claim from her phone. Run from the repository root:

    uv run python examples/claims/record.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from recording import Recording, Window, picture, served  # noqa: E402

PORT = 8033


def button(label: str, inside: str = "document") -> str:
    return f"[...{inside}.querySelectorAll('button')].find(b => b.textContent.trim() === '{label}')"


USERNAME = "document.querySelector('input')"
PASSWORD = "document.querySelector('input[type=password]')"


async def sign_in(window: Window, base: str, who: str) -> None:
    await window.go(base + "/")
    for field, text in ((USERNAME, who), (PASSWORD, "claims")):
        await window.eval(f"{field}.focus()")
        await window.call("Input.insertText", text=text)
    await window.eval(f"{button('Sign in')}.click()")
    await asyncio.sleep(1.5)


async def record(base: str) -> None:
    priya = Window(860, 740, zone="Europe/London")
    nora = Window(390, 780, zone="Europe/London", phone=True)
    await priya.open()
    await nora.open()
    try:
        # Nora is signed in on her phone. Priya's screen is at the door.
        await sign_in(nora, base, "nora")
        await priya.go(base + "/")
        film = Recording(priya, nora)
        await film.rest(0.8)

        # 1. Priya signs in, and lands on what waits for her.
        await film.click(priya, USERNAME)
        await film.type(priya, "priya")
        await film.click(priya, PASSWORD)
        await film.type(priya, "claims")
        await film.click(priya, button("Sign in"))
        await film.rest(1.6)

        # 2. Nora files a claim from her phone, with a photo of the ticket.
        await film.click(nora, button("New claim"))
        await film.rest(0.6)
        await nora.eval("document.getElementById('f_title').focus()")
        await film.type(nora, "Train to the workshop")
        await nora.eval("document.getElementById('f_amount').focus()")
        await film.type(nora, "94.40")
        await nora.attach("document.getElementById('f_receipt')", HERE / "receipts" / "train.png")
        await film.rest(0.9)
        await film.click(nora, button("Send to my manager"))
        # 3. It is in Priya's list as it is sent, and counted in her sidebar.
        await film.rest(1.8)

        # 4. Priya opens it. The receipt Nora photographed is beside the claim.
        row = "[...document.querySelectorAll('td')].find(e => e.textContent.includes('Train to'))"
        await film.click(priya, row)
        await film.rest(2.0)

        # 5. She approves it, and Nora's phone says so.
        await film.click(priya, button("Approve"))
        await film.rest(3.0)
    finally:
        await nora.close()
        await priya.close()
    out = HERE / "claims.gif"
    picture(out, [(priya, 24, 29, 860), (nora, 908, 134, 260)], backdrop="0xe4e7e2")
    print(f"{len(priya.frames)} frames, {out.name} {out.stat().st_size / 1e6:.2f} MB")


async def main() -> None:
    async with served(HERE / "app.py", PORT) as base:
        await record(base)


if __name__ == "__main__":
    asyncio.run(main())
