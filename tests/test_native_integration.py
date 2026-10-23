"""Checks that files written by pykeynote open in real Keynote and show the right text.

Needs macOS with Keynote and PYKEYNOTE_INTEGRATION=1.
"""

import os
import sys
from pathlib import Path

import pytest

from pykeynote import KeynoteError, Paragraph, Presentation
from pykeynote import scripting

FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = [
    pytest.mark.keynote,
    pytest.mark.skipif(
        sys.platform != "darwin" or os.environ.get("PYKEYNOTE_INTEGRATION") != "1",
        reason="needs macOS with Keynote and PYKEYNOTE_INTEGRATION=1",
    ),
]


@pytest.fixture
def open_in_keynote():
    opened = []

    def _open(path):
        deck = scripting.Presentation.open(path)
        opened.append(deck)
        return deck

    yield _open
    for deck in opened:
        try:
            deck.close()
        except KeynoteError:
            pass


def test_edited_text_opens_in_keynote(tmp_path, open_in_keynote):
    deck = Presentation.open(FIXTURES / "layouts-basic-white.key")
    deck[0].title = "Written by pykeynote 🤖"
    deck[3].title = "Robots"
    deck[3].body = [Paragraph("Fun", 0), Paragraph("Mostly", 1), "Useful", "Everywhere"]
    deck[3].notes = "Say hello\nThen start"
    deck[9].title = "A much longer title than the layout was made for, to check wrapping"
    out = tmp_path / "edited.key"
    deck.save(out)

    live = open_in_keynote(out)
    assert len(live) == 17
    rows = live.read_slides()
    assert rows[0]["title"] == "Written by pykeynote 🤖"
    assert rows[3]["title"] == "Robots"
    assert rows[3]["body"].replace("\r", "\n").split("\n") == ["Fun", "Mostly", "Useful", "Everywhere"]
    assert rows[3]["notes"].replace("\r", "\n") == "Say hello\nThen start"
    assert rows[9]["title"].startswith("A much longer title")


def test_resaved_by_keynote_reads_back(tmp_path, open_in_keynote):
    deck = Presentation.open(FIXTURES / "transitions-basic-white.key")
    deck[0].body = "One\nTwo\nThree"
    out = tmp_path / "edited.key"
    deck.save(out)

    live = open_in_keynote(out)
    resaved = tmp_path / "resaved.key"
    live.save(resaved)

    again = Presentation.open(resaved)
    assert again[0].body == "One\nTwo\nThree"
    assert again[0].transition.effect == "dissolve"


MARKDOWN = """# Robots!

Kevin McAleer

---

<!-- transition: dissolve 1.5s -->
# Why robots?

- Fun 🤖
  - Mostly
- Useful

???
Keep it short.

---

<!-- layout: Quote -->
Any sufficiently advanced robot is indistinguishable from a cat.

---

<!-- transition: magic move 1s -->
<!-- skipped -->
# Thanks
"""


def test_deck_from_markdown_opens_in_keynote(tmp_path, open_in_keynote):
    from pykeynote import from_markdown

    out = tmp_path / "from-markdown.key"
    from_markdown(MARKDOWN).save(out)

    live = open_in_keynote(out)
    rows = live.read_slides()
    assert [r["layout"] for r in rows] == ["Title", "Title & Bullets", "Quote", "Title Only"]
    assert rows[0]["title"] == "Robots!"
    assert rows[1]["body"].replace("\r", "\n").split("\n") == ["Fun 🤖", "Mostly", "Useful"]
    assert rows[1]["notes"] == "Keep it short."
    assert rows[3]["skipped"] is True

    resaved = tmp_path / "resaved.key"
    live.save(resaved)
    again = Presentation.open(resaved)
    assert again.to_markdown() == Presentation.open(out).to_markdown()


def test_slide_operations_open_in_keynote(tmp_path, open_in_keynote):
    deck = Presentation.open(FIXTURES / "layouts-basic-white.key")
    deck.duplicate_slide(3).title = "Copy"
    deck.move_slide(4, 0)
    deck.delete_slide(-1)
    deck.delete_slide(5)
    out = tmp_path / "ops.key"
    deck.save(out)
    expected = [s.title for s in Presentation.open(out)]

    live = open_in_keynote(out)
    assert [r["title"] for r in live.read_slides()] == expected
