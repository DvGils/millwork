"""The app behind the README's pictures: an orders desk with a form, an import
that reports progress, a table that fills as rows arrive, and a chat that
streams its answer. ``record.py`` drives it and writes the screenshots and
the GIF, so what the README shows is what this file does."""

import asyncio

from pydantic import BaseModel, Field

import millwork as mw
from millwork import ui

INCOMING = [
    ("Halvard", 2310.0, "paid"),
    ("Pell Street", 460.0, "open"),
    ("Lumen Labs", 1200.0, "paid"),
    ("Marrow & Vine", 980.0, "open"),
    ("Tessellate", 1740.0, "paid"),
]


class Order(BaseModel):
    customer: str = Field(min_length=2)
    amount: float


class State(BaseModel):
    orders: list[dict] = [
        {"id": 1041, "customer": "Wren & Co", "amount": 840.0, "status": "paid"},
        {"id": 1042, "customer": "Ostrava Press", "amount": 310.0, "status": "open"},
    ]
    importing: mw.Task | None = None


app = mw.App("Orders", state=State, public=None)


def add(s: mw.Session[State], order: Order) -> None:
    if order.amount <= 0:
        raise ui.FormIssues([("/amount", "An amount is positive.")])
    s.state.orders.append(
        {
            "id": 1041 + len(s.state.orders),
            "customer": order.customer,
            "amount": order.amount,
            "status": "open",
        }
    )
    s.toast(f"Saved {order.customer}.", tone="success")


async def pull(s: mw.Session[State]) -> str:
    p = mw.progress()
    p.plan(["Connect", "Fetch", "Reconcile"])
    with p.step("Connect"):
        await asyncio.sleep(0.5)
    with p.step("Fetch") as step:
        for i, (customer, amount, status) in enumerate(INCOMING):
            p.check()
            await asyncio.sleep(0.45)
            s.state.orders.append(
                {
                    "id": 1041 + len(s.state.orders),
                    "customer": customer,
                    "amount": amount,
                    "status": status,
                }
            )
            p.set((i + 1) / len(INCOMING), f"{i + 1} of {len(INCOMING)} orders")
            s.refresh()
        step.note(f"{len(INCOMING)} orders")
    with p.step("Reconcile"):
        await asyncio.sleep(0.5)
    return f"{len(INCOMING)} orders imported"


def start_import(s: mw.Session[State], _: object) -> None:
    s.state.importing = s.task(pull(s), label="Importing orders")


async def answer(s: mw.Session[State], turn: mw.ChatTurn) -> None:
    totals: dict[str, float] = {}
    for o in s.state.orders:
        totals[o["customer"]] = totals.get(o["customer"], 0.0) + o["amount"]
    top = max(totals, key=lambda c: totals[c])
    async with turn.reply() as reply:
        async with reply.step("Summing orders by customer") as step:
            await asyncio.sleep(0.6)
            await step.output({"customers": len(totals)})
        count = sum(1 for o in s.state.orders if o["customer"] == top)
        open_total = sum(o["amount"] for o in s.state.orders if o["status"] == "open")
        words = (
            f"**{top}** has the most on the books, {totals[top]:,.0f} euros across "
            f"{count} order{'s' if count != 1 else ''}. "
            f"Open orders add up to {open_total:,.0f} euros."
        ).split(" ")
        for word in words:
            await reply.text(word + " ")
            await asyncio.sleep(0.06)


@app.page("/", title="Orders")
def home(s: mw.Session[State]) -> ui.Component:
    st = s.state
    revenue = sum(o["amount"] for o in st.orders if o["status"] == "paid")
    open_orders = [o for o in st.orders if o["status"] == "open"]
    running = st.importing is not None and not st.importing.done
    return ui.Page(
        ui.Grid(
            ui.Stat(
                label="Revenue",
                value=f"€ {revenue:,.0f}",
                delta=0.12,
                trend=[52, 48, 55, 51, 63, 70],
            ),
            ui.Stat(label="Orders", value=str(len(st.orders)), delta=3, delta_format="number"),
            ui.Stat(
                label="Open",
                value=f"€ {sum(o['amount'] for o in open_orders):,.0f}",
                delta=-0.08,
                good="down",
            ),
            cols={"sm": 1, "md": 3},
        ),
        ui.Grid(
            ui.Card(
                ui.Row(
                    ui.Button("Import", icon="download", on_click=start_import, disabled=running),
                    ui.Progress(task=st.importing, cls="grow") if st.importing else None,
                    gap=4,
                ),
                ui.Steps(task=st.importing) if st.importing else None,
                ui.Table(
                    rows=st.orders,
                    columns=[
                        ui.Column(key="id", header="Order"),
                        ui.Column(key="customer"),
                        ui.Column(key="amount", format="currency", align="right"),
                        ui.Column(key="status", format="badge"),
                    ],
                    default_sort=[("id", "desc")],
                    tones={"status": lambda r, v: "success" if v == "paid" else "warning"},
                    key="orders",
                ),
                title="Orders",
                description="What came in, and what an import adds as it runs.",
            ),
            ui.Stack(
                ui.Card(
                    # A new key per saved order: the form that saved one is done,
                    # and a fresh one takes its place with empty fields.
                    ui.Form(Order, on_submit=add, submit="Add", key=f"order-{len(st.orders)}"),
                    title="New order",
                ),
                ui.Card(
                    ui.Chat(
                        key="ask",
                        welcome="Ask about the orders. The answer streams from Python.",
                        placeholder="Which customer spent most?",
                        on_message=answer,
                        cls="h-72",
                    ),
                    title="Ask",
                    padding=False,
                ),
                gap=6,
            ),
            cols={"sm": 1, "lg": 2},
        ),
        gap=6,
        header=ui.Header(title="Orders", user_menu=False),
    )
