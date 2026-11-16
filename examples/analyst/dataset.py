"""The data the analyst works on. Each session gets a SQLite database of
its own, in memory, with a year and a half of a small shop's orders in it
and whatever tables the person adds from CSV files.

A query from the analyst is one statement that may only read. It is
stopped when it runs longer than a second, it gives back a few hundred
rows at most, and no value in it is longer than a hundred thousand
characters. The SQL comes from a model or from a script, about data that
may be a person's own file, and none of it is taken at its word."""

from __future__ import annotations

import csv
import io
import random
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

FIRST, LAST = date(2025, 1, 1), date(2026, 6, 30)
REGIONS = ("North", "South", "East", "West")
# What the shop sells, with the price of one.
PRODUCTS = {"Lantern": 34.0, "Compass": 19.5, "Flask": 24.0, "Tarp": 58.0, "Stove": 89.0}

# What a query may do, which is read. Everything else is refused.
READS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}


# The longest a text or a blob may be, and the most columns a result or a
# table may have. Without these one query could ask for a value of a
# gigabyte, which no time limit stops.
LONGEST, WIDEST = 100_000, 50


class Refused(Exception):
    """Something that was not done, with words for whoever asked."""


@dataclass
class Result:
    columns: list[str]
    rows: list[dict[str, Any]]
    # Whether there were more rows than were given.
    more: bool = False


def _orders() -> list[tuple[str, str, str, str, int, float]]:
    """The shop's orders, the same every time. Sales grow a little each
    month and are higher in summer, and in March 2026 the West had no
    tarps and no stoves to sell."""
    dice = random.Random(7)
    rows = []
    day = FIRST
    while day <= LAST:
        months_in = (day.year - FIRST.year) * 12 + day.month - 1
        season = 1.25 if day.month in (6, 7, 8) else 1.0
        for region in REGIONS:
            for product, price in PRODUCTS.items():
                units = round(dice.uniform(2, 9) * season * (1 + months_in * 0.02))
                if region == "West":
                    units = round(units * 1.3)
                    if product in ("Tarp", "Stove") and (day.year, day.month) == (2026, 3):
                        units = 0
                if units:
                    channel = dice.choice(("online", "online", "store"))
                    rows.append(
                        (day.isoformat(), region, product, channel, units, round(units * price, 2))
                    )
        day += timedelta(days=1)
    return rows


_TEMPLATE = sqlite3.connect(":memory:", check_same_thread=False)
_TEMPLATE.execute(
    "CREATE TABLE orders (day TEXT, region TEXT, product TEXT, channel TEXT,"
    " units INTEGER, revenue REAL)"
)
_TEMPLATE.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)", _orders())
_TEMPLATE.commit()


def fresh() -> sqlite3.Connection:
    """A database for one session, with the shop's orders in it."""
    db = sqlite3.connect(":memory:", check_same_thread=False)
    _TEMPLATE.backup(db)
    db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, LONGEST)
    db.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, WIDEST)
    return db


def tables(db: sqlite3.Connection) -> dict[str, list[str]]:
    """The tables there are, each with its columns."""
    names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    return {name: [col[1] for col in db.execute(f'PRAGMA table_info("{name}")')] for name in names}


def query(db: sqlite3.Connection, sql: str, limit: int = 200, seconds: float = 1.0) -> Result:
    """Run one statement that only reads, and give its rows."""
    deadline = time.monotonic() + seconds
    db.set_authorizer(
        lambda action, *_: sqlite3.SQLITE_OK if action in READS else sqlite3.SQLITE_DENY
    )
    db.set_progress_handler(lambda: time.monotonic() > deadline, 10_000)
    try:
        cursor = db.execute(sql)
        if cursor.description is None:
            raise Refused("That is not a query that gives rows.")
        columns = [column[0] for column in cursor.description]
        rows = cursor.fetchmany(limit + 1)
    except sqlite3.Error as error:
        raise Refused(str(error)) from None
    finally:
        db.set_authorizer(None)
        db.set_progress_handler(None, 0)
    # Bytes are no value a page or a model can show, so they are named.
    shown = [[f"<{len(v)} bytes>" if isinstance(v, bytes) else v for v in row] for row in rows]
    found = [dict(zip(columns, row, strict=True)) for row in shown[:limit]]
    return Result(columns, found, more=len(rows) > limit)


def load_csv(
    db: sqlite3.Connection, filename: str, text: str, most: int = 50_000
) -> tuple[str, int]:
    """Make a table of a CSV file, named after the file, and give its name
    and how many rows it got. A column of numbers is a column of numbers."""
    name = _named(filename.rsplit(".", 1)[0]) or "upload"
    if name in tables(db):
        raise Refused(f"There is a table {name} already.")
    if name.startswith("sqlite_"):
        raise Refused(f"A table cannot be called {name}.")
    try:
        read = csv.reader(io.StringIO(text))
        header = next(read, None)
        body = [row for row in read if row]
    except csv.Error as error:
        raise Refused(f"That is not a CSV file this can read. {error}") from None
    if not header or not body:
        raise Refused("That file has no rows under a line of column names.")
    if len(body) > most:
        raise Refused(f"That file has more than {most:,} rows.")
    columns = [_named(column) or f"column_{n + 1}" for n, column in enumerate(header)]
    if len(set(columns)) != len(columns) or len(columns) > WIDEST:
        raise Refused(f"A file's columns need names of their own, and {WIDEST} of them at most.")
    width = len(columns)
    body = [(row + [""] * width)[:width] for row in body]
    numbers = [all(_number(row[n]) is not None for row in body) for n in range(width)]
    kinds = ", ".join(
        f'"{c}" {"REAL" if n else "TEXT"}' for c, n in zip(columns, numbers, strict=True)
    )
    try:
        db.execute(f'CREATE TABLE "{name}" ({kinds})')
        db.executemany(
            f'INSERT INTO "{name}" VALUES ({", ".join("?" * width)})',
            [[_number(v) if n else v for v, n in zip(row, numbers, strict=True)] for row in body],
        )
        db.commit()
    except sqlite3.Error as error:
        db.rollback()
        db.execute(f'DROP TABLE IF EXISTS "{name}"')
        raise Refused(f"That file could not be made a table. {error}") from None
    return name, len(body)


def _named(text: str) -> str:
    """A name a table or a column can have: letters, digits and underscores."""
    return re.sub(r"\W+", "_", text.strip().lower()).strip("_")[:40]


def _number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None
