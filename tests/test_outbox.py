"""The outbox: numbered, kept for replay within a window, and shut for good
once sealed."""

from millwork.outbox import GAP, Outbox
from millwork.protocol import Command


def note(n: int, size: int = 0) -> Command:
    return Command(name="note", args={"n": n, "pad": "x" * size})


def test_messages_are_numbered_and_handed_out_from_where_a_tab_is() -> None:
    box = Outbox()
    for n in range(1, 6):
        assert box.post(note(n))
    assert box.seq == 5 and box.posted == 5
    assert [seq for seq, _ in box.after(0)] == [1, 2, 3, 4, 5]
    assert [seq for seq, _ in box.after(3)] == [4, 5]
    assert box.after(5) == []
    assert '"n":4' in box.after(3)[0][1]


def test_a_tab_behind_the_window_or_ahead_of_it_cannot_be_caught_up() -> None:
    box = Outbox(keep=3)
    for n in range(1, 8):
        box.post(note(n))
    assert [seq for seq, _ in box.after(4)] == [5, 6, 7]
    assert box.after(3) is GAP
    assert box.after(0) is GAP
    assert box.after(9) is GAP


def test_the_window_is_bounded_in_bytes_too_and_always_keeps_the_last() -> None:
    box = Outbox(keep=100, keep_bytes=2500)
    for n in range(1, 6):
        box.post(note(n, size=1000))
    assert [seq for seq, _ in box.after(3)] == [4, 5]
    assert box.after(2) is GAP
    box.post(note(6, size=5000))
    assert [seq for seq, _ in box.after(5)] == [6]


def test_a_sealed_outbox_takes_nothing_and_hands_out_nothing() -> None:
    box = Outbox()
    box.post(note(1))
    box.seal()
    assert not box.post(note(2))
    assert box.seq == 1 and box.posted == 1
    assert box.after(0) is GAP and box.after(1) == []


def test_whoever_follows_is_poked_when_there_is_something_new() -> None:
    box = Outbox()
    pokes: list[int] = []
    box.poke = lambda: pokes.append(box.seq)
    box.post(note(1))
    box.post(note(2))
    box.seal()
    assert pokes == [1, 2, 2]
