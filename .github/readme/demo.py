"""The app behind the README's pictures: an orders desk with a form, an import
that reports progress, a table and a chart that follow the rows as they
arrive, and a chat in a floating window that streams its answer and points
at the figure it is about.
``record.py`` drives it and writes the GIF, so what the README shows is what
this file does."""

import asyncio

from pydantic import BaseModel, Field

import millwork as mw
from millwork import ui

# What the three figures at the top are held against.
LAST_WEEK = {"revenue": 5400.0, "orders": 6, "open": 2400.0}

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
    # A line under the bar from the first moment, so nothing under it moves.
    p.set(0, f"0 of {len(INCOMING)} orders")
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
    owing = [o for o in s.state.orders if o["status"] == "open"]
    async with turn.reply() as reply:
        async with reply.step("Looking up open orders") as step:
            await asyncio.sleep(0.6)
            await step.output({"open": len(owing)})
        if not owing:
            await reply.text("Nothing. Every order is paid.")
            return
        total = sum(o["amount"] for o in owing)
        count = "One order is" if len(owing) == 1 else f"{len(owing)} orders are"
        for word in f"**{count} still open**, {total:,.0f} euros in all.".split(" "):
            await reply.text(word + " ")
            await asyncio.sleep(0.06)
        # And where that is on the page: a frame around the figure, with a
        # light that goes around it.
        s.highlight("open", "orange", style="trace")
        for word in "I've highlighted the card that shows it in orange.".split(" "):
            await reply.text(word + " ")
            await asyncio.sleep(0.06)


@app.page("/", title="Orders")
def home(s: mw.Session[State]) -> ui.Component:
    st = s.state
    revenue = sum(o["amount"] for o in st.orders if o["status"] == "paid")
    owed = sum(o["amount"] for o in st.orders if o["status"] == "open")
    # What was paid after each order, for the line beside the revenue.
    paid_so_far: list[float] = []
    for o in st.orders:
        last = paid_so_far[-1] if paid_so_far else 0.0
        paid_so_far.append(last + (o["amount"] if o["status"] == "paid" else 0.0))
    running = st.importing is not None and not st.importing.done
    # What each customer has on the books, the largest first.
    totals: dict[str, float] = {}
    for o in st.orders:
        totals[o["customer"]] = totals.get(o["customer"], 0.0) + o["amount"]
    largest = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:5]
    return ui.Page(
        ui.Grid(
            ui.Stat(
                label="Revenue",
                value=f"€ {revenue:,.0f}",
                delta=revenue / LAST_WEEK["revenue"] - 1,
                trend=paid_so_far,
                hint="against last week",
            ),
            ui.Stat(
                label="Orders",
                value=str(len(st.orders)),
                delta=len(st.orders) - LAST_WEEK["orders"],
                delta_format="number",
                hint="against last week",
            ),
            ui.Stat(
                label="Open",
                value=f"€ {owed:,.0f}",
                delta=owed / LAST_WEEK["open"] - 1,
                good="down",
                hint="against last week",
                key="open",
            ),
            cols={"sm": 1, "md": 3},
        ),
        # Two columns that keep their size while the page works. The bar takes
        # the room beside the button, and the card has the room for the steps
        # that come in above the table when an import starts.
        ui.Grid(
            ui.Card(
                ui.Row(
                    ui.Button("Import", icon="download", on_click=start_import, disabled=running),
                    ui.Progress(task=st.importing, cls="grow") if st.importing else None,
                    gap=4,
                    cls="min-h-14",
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
                    height=312,
                    key="orders",
                ),
                title="Orders",
                # As tall with two orders as with eight.
                cls="min-h-[597px]",
            ),
            ui.Stack(
                ui.Card(
                    ui.BarChart(
                        [{"customer": name, "amount": amount} for name, amount in largest],
                        x="customer",
                        y="amount",
                        format="currency",
                        horizontal=True,
                        labels=True,
                        legend=False,
                        animate=True,
                        height=170,
                        key="largest",
                    ),
                    title="Largest customers",
                ),
                ui.Card(
                    # A new key per saved order: the form that saved one is done,
                    # and a fresh one takes its place with empty fields.
                    ui.Form(
                        Order, on_submit=add, submit="Add", layout=2, key=f"order-{len(st.orders)}"
                    ),
                    title="New order",
                    cls="grow",
                ),
                gap=6,
            ),
            cols={"sm": 1, "lg": 2},
        ),
        # The chat is a button in the corner until someone has a question.
        ui.Assistant(
            ui.Chat(
                key="ask",
                welcome="The answer streams from Python.",
                placeholder="Ask about the orders",
                on_message=answer,
            ),
            label="Ask about the orders",
            title="Ask",
            key="assistant",
        ),
        gap=6,
        header=ui.Header(title="Orders", user_menu=False),
    )
