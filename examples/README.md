# Examples

Whole apps, each in a directory of its own, each with tests and a
picture of it in use.

- [Team chat](chat/): channels, messages that arrive as they are sent,
  who is typing and who is here.

An example runs from the repository root:

```
uv run millwork run examples/chat/app.py
```

`uv run pytest examples` runs their tests. A test file is named after
its example, as `test_team_chat.py` is, since pytest wants a name that no
other test file in the repository has. A picture is made by the example's
own `record.py`, with what is in `recording.py`.
