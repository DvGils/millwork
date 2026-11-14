"""A page with the kinds of component that say something on it, in the
states that change what the page as data says of them."""

from typing import Any, Literal

from pydantic import BaseModel, Field

import millwork as mw
from millwork import ui


class Line(BaseModel):
    sku: str = Field(title="Article")
    qty: int = 1


class Address(BaseModel):
    street: str
    city: str = Field(description="Where it is sent to.")


class Order(BaseModel):
    """A new order."""

    kind: Literal["order"] = "order"
    customer: str = Field(title="Customer")
    amount: float = Field(ge=0, description="What the customer pays, without tax.")
    tier: Literal["gold", "silver"] = "silver"
    pin: str = Field("", json_schema_extra={"widget": "password"})
    address: Address
    lines: list[Line] = []


class State(BaseModel):
    adding: bool = False
    note: str = "as typed"
    tab: str = "paid"
    customer: str | None = "cus_8f3a"
    nothing: str | None = None
    tags: list[str] = ["t1", "t3"]


ROWS = [
    {
        "id": 1,
        "customer": "Kestrel, Books",
        "amount": 1234.5678,
        "margin": 0.31,
        "since": "2026-01-05T13:44:21",
        "paid": True,
        "share": 0.3141,
        "due": 1234567.891,
    },
    {
        "id": 2,
        "customer": "Juniper Press",
        "amount": 120,
        "margin": 0.12,
        "since": None,
        "paid": False,
        "share": 0.05,
        "due": float("nan"),
    },
    {
        "id": 3,
        "customer": "Alder | Co",
        "amount": 2.5,
        "margin": 0.4,
        "since": "x" * 300,
        "paid": True,
        "share": 12,
        "due": 0,
    },
]
CUSTOMERS = [("cus_8f3a", "Kestrel Books"), ("cus_11b2", "Juniper Press")]
TAGS = [(f"t{n}", f"Tag {n}") for n in range(1, 16)]
SALES = [
    {"month": "Jan", "north": 1234567.5, "south": 0.25},
    {"month": "Feb", "north": 2, "south": None},
    {"month": "Mar", "north": 3, "south": 4},
]


class PatientCard(mw.Component):
    """A component of the app's own, drawn by a file of the app's."""

    type = "PatientCard"
    title: str = ""
    description: str = ""


class LoudButton(ui.Button):
    """A button of the app's with something more on it."""

    record: str = ""


def nothing(s: Any, *_: Any) -> None:
    return None


def make_app() -> mw.App:
    app = mw.App("orders", state=State, public=None)

    async def ask(s: mw.Session[State], _: Any) -> None:
        await s.confirm("Archive the order?")

    def add(s: mw.Session[State], _: Any) -> None:
        s.state.adding = True

    def leave(s: mw.Session[State], _: Any) -> None:
        s.state.adding = False

    def place(s: mw.Session[State], order: Order) -> None:
        if order.customer == "nobody":
            raise ui.FormIssues([("/customer", "No such customer.")])

    @app.page("/")
    def home(s: mw.Session[State]) -> ui.Component:
        return ui.Page(
            ui.Sidebar(
                ui.SidebarGroup(ui.Link(label="Orders", href="/", active=True), label="Shop"),
                ui.SidebarGroup(ui.Link(label="Stock", href="/stock"), label="Depot", open=False),
                ui.SidebarGroup(
                    ui.Link(label="Help", href="/help"), label="More", open=False, collapsible=False
                ),
                title="Acme",
                open=False,
            ),
            ui.Stack(
                ui.Button("New order", key="new", on_click=add),
                ui.Button("Ask", key="ask", on_click=ask),
                ui.Button("Export", disabled=True),
                ui.Button(icon="trash-2", tooltip="Delete the order", key="bin"),
                ui.Button(icon="plus", key="plus", confirm="Sure?", loading=True),
                ui.Button("Place", form="order", key="place"),
                ui.Button("Go", href="/placed?x=1 2", key="go"),
                LoudButton("Loud", record="rec_1", key="loud"),
                ui.Download("Get the list", filename="orders 2026.csv", content=b"x", key="csv"),
                ui.DropdownMenu(
                    trigger=ui.Button("More", key="menu-button"),
                    items=[ui.MenuItem(id="a", label="Archive"), ui.MenuItem(id="d", label="Drop")],
                    key="menu",
                ),
                ui.Input(key="held", value=s.state.note, on_change=nothing, suffix="kg"),
                ui.Input(key="loose", default="in the browser", placeholder="Anything"),
                ui.Input(key="secret", kind="password", value="hunter2"),
                ui.Input(key="mail", kind="email", value="", readonly=True),
                ui.Textarea(key="long", value="one\ntwo  three", disabled=True),
                ui.NumberInput(key="count", value=3, min=0, max=10, suffix="pcs"),
                ui.Slider(key="level", value=40, min=0, max=100),
                ui.DatePicker(key="day", value="2026-01-05", min="2026-01-01"),
                ui.Select(options=CUSTOMERS, value=s.state.customer, key="who"),
                ui.Select(options=CUSTOMERS, value=s.state.nothing, key="nobody"),
                ui.Select(options=CUSTOMERS, value="cus_gone", key="stale"),
                ui.Combobox(value="cus_8f3a", on_search=lambda s, q: [], key="searched"),
                ui.MultiSelect(options=TAGS, value=s.state.tags, key="tags", placeholder="Tags"),
                ui.RadioGroup(options=["Mail", "Courier"], value="Courier", label="Sent by"),
                ui.CheckboxGroup(options=["Wrap", "Card"], value=["Wrap", "Bow"], label="With"),
                ui.ToggleGroup(options=[("l", "List"), ("g", "Grid")], value="g", key="view"),
                ui.Checkbox(label="Rush", description="Next day", checked=True, key="rush"),
                ui.Switch(label="Gift", checked=False, key="gift"),
                ui.Switch(label="Loose", key="loose-switch"),
                ui.FileUpload(label="Proof", accept=[".pdf", "image/*"], key="proof"),
                ui.Field(
                    ui.Input(key="vat"), label="VAT", help="As on the bill", error="Too short"
                ),
                ui.Text("Not for the screen", key="gone", hidden=True),
                ui.Stack(
                    ui.Button("Inside", key="inside"),
                    ui.Button("Twice", key="twice"),
                    key="shut",
                    hidden=True,
                ),
                ui.Button("Twice", key="twice"),
                ui.Button("Leave it", key="leave", on_click=leave),
            ),
            ui.Table(
                rows=ROWS,
                columns=[
                    ui.Column(key="customer", header="Customer"),
                    ui.Column(key="amount", format="integer"),
                    ui.Column(key="since", format="date"),
                    ui.Column(key="paid", format="bool"),
                    ui.Column(key="share", format="percent", header=""),
                    ui.Column(key="due", format="currency"),
                    ui.Column(key="due", format="number", header="Due, exact"),
                    ui.Column(key="id", hidden=True),
                ],
                selection="rows",
                selected=[2],
                row_actions=[ui.MenuItem(id="rm", label="Remove")],
                default_sort=[("amount", "desc")],
                page_size=2,
                search=True,
                filters=True,
                summary="Open orders",
                on_row_click=nothing,
                key="orders",
            ),
            ui.Table(rows=[], columns=[ui.Column(key="a")], empty="Nothing yet", key="none"),
            ui.BarChart(SALES, x="month", y=["north", "south"], format="integer", key="sales"),
            ui.PieChart(SALES, x="month", y="north", key="pie"),
            ui.Card(
                ui.Button("Edit", key="edit"),
                title="First",
                description="The first card",
                footer=ui.Button("Done", key="done"),
                key="one",
            ),
            ui.Card(ui.Button("Edit", key="edit"), title="Second", key="two"),
            ui.Tabs(
                ui.Tab(ui.Text("The open ones"), id="open", label="Open"),
                ui.Tab(ui.Text("The paid ones"), id="paid", label="Paid", badge="3"),
                ui.Tab(ui.Text("The old ones"), id="old", label="Old", disabled=True),
                value=s.state.tab,
                on_change=nothing,
                key="which",
            ),
            ui.Tabs(
                ui.Tab(ui.Text("Left"), id="l", label="Left"),
                ui.Tab(ui.Text("Right"), id="r", label="Right"),
                key="free",
            ),
            ui.Collapsible(ui.Text("More of it"), title="More", open=False, key="more"),
            ui.Collapsible(ui.Text("Out in the open"), title="Open", open=True, key="open"),
            ui.Collapsible(ui.Text("Who knows"), title="Maybe", key="maybe"),
            ui.Accordion(
                ui.AccordionItem(ui.Text("First answer"), id="q1", title="First question"),
                ui.AccordionItem(ui.Text("Second answer"), id="q2", title="Second question"),
                value=["q2"],
                on_change=nothing,
                key="faq",
            ),
            ui.Accordion(
                ui.AccordionItem(ui.Text("Loose answer"), id="q", title="Loose question"),
                key="loose-faq",
            ),
            ui.Alert(
                title="Late",
                description="Two orders are late.",
                actions=[ui.Button("See them", key="see")],
            ),
            ui.Empty(title="No stock", description="Nothing here.", action=ui.Button("Add")),
            ui.Stat(label="Revenue", value="12,400", hint="this month", delta=-0.125),
            ui.Stat(label="Orders", value="18", delta=1234567, delta_format="number"),
            ui.Progress(value=0.415, label="Packing", description="5 of 12"),
            ui.Steps(
                items=[
                    mw.Step(id=str(n), label=f"Step {n}", status="done" if n < 15 else "pending")
                    for n in range(1, 21)
                ]
            ),
            ui.Steps(items=[mw.Step(id="p", label="Pick", status="running", note="aisle 4")]),
            ui.FileCard(
                name="bill.pdf", meta="2 pages", actions=[ui.MenuItem(id="o", label="Open")]
            ),
            ui.Text("Plain   words\nhere"),
            ui.Markdown("# Title\n\nSome *words*."),
            ui.Code("print(1)", title="Example"),
            ui.Kbd(keys=["Ctrl", "K"]),
            ui.Badge("New"),
            ui.Separator(label="or"),
            ui.Separator(),
            ui.Icon(name="star", label="Starred"),
            ui.Icon(name="star"),
            ui.Image(src="/a.png", alt="A map"),
            ui.Image(src="/b.png", on_click=nothing),
            ui.Spinner(),
            ui.Skeleton(),
            ui.Tooltip(ui.Button("Hover", key="hover"), content="Shown on hover"),
            ui.Link(label="Docs", href="https://example.com/docs"),
            ui.Custom("Hello", ui.Text("Held by the app's own"), key="mine", props={"label": "x"}),
            PatientCard(title="not said either", description="nor this", key="theirs"),
            ui.Form(
                Order,
                initial={
                    "customer": "Kestrel Books",
                    "amount": 12.5,
                    "tier": "gold",
                    "pin": "4711",
                    "address": {"street": "Mill Lane 1", "city": "Delft"},
                    "lines": [{"sku": "A-1", "qty": 2}],
                },
                read_only=True,
                key="record",
            ),
            ui.Dialog(
                ui.Form(Order, key="order", submit="Place it", cancel="Leave", on_submit=place),
                open=s.state.adding,
                title="New order",
                description="For a customer",
                footer=ui.Button("Save", key="save"),
                key="dlg",
            ),
            ui.Row(ui.Badge("In a row"), ui.ButtonGroup(ui.Button("One"), ui.Button("Two"))),
            ui.Grid(ui.Text("In a grid"), ui.ScrollArea(ui.Text("Scrolled"))),
            ui.Split(ui.Text("Left pane"), ui.Text("Right pane")),
            ui.LineChart(SALES, x="month", y="north", format="currency", key="line"),
            ui.AreaChart(SALES, x="month", y="south", format="percent", key="area"),
            ui.Chat(welcome="Ask about an order", suggestions=["Where is it?"], key="chat"),
            ui.Sheet(ui.Text("On the side"), title="Details", key="side"),
            ui.Assistant(
                ui.Text("Ask away"), label="Help", title="Ask the docs", open=False, key="helper"
            ),
            title="Orders",
            header=ui.Header(title="Acme", links=[ui.Link(label="Home", href="/")]),
        )

    @app.page("/other")
    def other(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Text("Another page"))

    @app.page("/shut")
    def shut(s: mw.Session[State]) -> ui.Component:
        return ui.Page(ui.Text("Never shown"))

    @shut.connect
    def refuse(s: mw.Session[State]) -> None:
        raise RuntimeError("no way in")

    return app


DRAFT = {
    "customer": "nobody",
    "amount": 5,
    "tier": "gold",
    "address": {"street": "Mill Lane 1", "city": "Delft"},
    "lines": [],
}


async def texts() -> dict[str, str]:
    """The page as text, in the states that are kept in ``outline_page.txt``."""
    from millwork.testing import TestApp

    out: dict[str, str] = {}
    async with TestApp(make_app()).open("/") as page:
        out["as it opens"] = page.outline(as_text=True)
        out["one row, twelve characters"] = page.outline(as_text=True, rows=1, chars=12)
        await page.click("new")
        await page.submit("order", DRAFT)
        out["its dialog open, and a submit turned down"] = page.outline(within="dlg", as_text=True)
    return out


def written(texts: dict[str, str]) -> str:
    return "".join(f"== {name} ==\n{text}\n\n" for name, text in texts.items())


if __name__ == "__main__":
    # uv run python tests/outline_page.py > tests/outline_page.txt
    import asyncio

    print(written(asyncio.run(texts())), end="")
