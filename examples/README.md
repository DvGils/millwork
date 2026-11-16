# Examples

Whole apps, each in a directory of its own, each with tests and a
picture of it in use.

- [Team chat](chat/): channels, messages that arrive as they are sent,
  who is typing and who is here.
- [Expense claims](claims/): sign-in for three kinds of people, a claim
  with its receipt that is filed, reviewed and paid, and a report that
  prints.
- [Analyst](analyst/): a chat that answers questions about a table of
  orders, pins charts to a board and points at them. It runs on a script,
  or on a model when it has a key.
- [Microscope](microscope/): a drop of water in which cells eat, divide
  and change over the generations, seen through a microscope whose lamp
  feeds what it shows.

An example runs from the repository root:

```
uv run millwork run examples/chat/app.py
```

`uv run pytest examples` runs their tests. A test file is named after
its example, as `test_team_chat.py` is, since pytest wants a name that no
other test file in the repository has. A picture is made by the example's
own `record.py`, with what is in `recording.py`.
