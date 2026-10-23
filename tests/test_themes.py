from pathlib import Path

import pytest

from pykeynote import Paragraph, Presentation, from_markdown, themes
from pykeynote.document import _bundled

from test_slides import check_consistent, reopen

FIXTURES = Path(__file__).parent / "fixtures"
SIZES = {"16:9": (1920, 1080), "4:3": (1024, 768)}


def other_theme(than):
    others = [t for t in themes() if t != than]
    return others[0] if others else than


@pytest.mark.parametrize("theme, aspect", _bundled())
def test_every_bundled_theme(theme, aspect, tmp_path):
    deck = Presentation.new(theme, aspect)
    assert deck.theme == theme
    assert deck.size == SIZES[aspect]
    assert len(deck) == 0
    # Every theme can stand in for each kind of slide.
    for title, body in [(True, True), (True, False), (False, True), (False, False)]:
        deck.add_slide(deck.match_layout("Nonexistent", title, body),
                       title="Title" if title else None, body="One\nTwo" if body else None)
    again = reopen(deck, tmp_path)
    assert again.theme == theme
    assert [s.title for s in again] == ["Title", "Title", None, None]
    assert [s.body for s in again] == ["One\nTwo", None, "One\nTwo", None]
    check_consistent(again)


def test_both_aspects_for_every_theme():
    for theme in themes():
        assert {a for t, a in _bundled() if t == theme} == set(SIZES)


def test_unknown_theme():
    with pytest.raises(ValueError, match="no bundled theme"):
        Presentation.new("Comic Sans Deluxe")


def test_match_layout():
    deck = Presentation.new()
    assert deck.match_layout("Agenda", title=True, body=True) == "Agenda"
    assert deck.match_layout("Bullets", title=True, body=True) == "Title & Bullets"
    assert deck.match_layout("Fancy", title=True) == "Title Only"
    assert deck.match_layout("Fancy", body=True) == "Bullets"
    assert deck.match_layout("Fancy") == "Blank"


def test_apply_theme_keeps_content(tmp_path):
    deck = Presentation.open(FIXTURES / "builds-talk.key")
    before = [(s.layout, s.title, [(p.text, p.level) for p in s.paragraphs], s.notes, s.transition, s.skipped)
              for s in deck]
    theme = other_theme(deck.theme)
    deck.apply_theme(theme, "4:3")
    again = reopen(deck, tmp_path)
    assert again.theme == theme
    assert again.size == (1024, 768)
    after = [(s.layout, s.title, [(p.text, p.level) for p in s.paragraphs], s.notes, s.transition, s.skipped)
             for s in again]
    assert after == before
    # Builds on the title and body come along; the one on a text box doesn't.
    builds = again[0].builds
    assert [(b.target, b.effect, b.delivery, b.steps) for b in builds] == [("body", "dissolve", "By Paragraph", 3)]
    check_consistent(again)


def test_apply_theme_keeps_aspect_by_default(tmp_path):
    deck = Presentation.new(aspect="4:3")
    deck.add_slide("Title", title="Hello")
    deck.apply_theme(other_theme("Basic White"))
    assert deck.size == (1024, 768)
    wide = Presentation.open(FIXTURES / "layouts-basic-white-wide.key")
    wide.apply_theme(other_theme("Basic White"))
    assert wide.size == (1920, 1080)


def test_apply_theme_maps_layouts(tmp_path):
    deck = Presentation.new()
    deck.add_slide("Title & Bullets", title="A", body=[Paragraph("x"), Paragraph("y", 1)])
    deck.add_slide("Quote", body="To be or not to be")
    deck.apply_theme(other_theme("Basic White"), layouts={"Quote": "Statement"})
    assert [s.layout for s in deck] == ["Title & Bullets", "Statement"]
    assert deck[1].body == "To be or not to be"
    # The deck can still have slides added and be saved.
    deck.add_slide("Title Only", title="More")
    again = reopen(deck, tmp_path)
    assert [s.title for s in again] == ["A", None, "More"]
    assert [(p.text, p.level) for p in again[0].paragraphs] == [("x", 0), ("y", 1)]
    check_consistent(again)


def test_apply_theme_errors():
    deck = Presentation.new()
    deck.add_slide("Title", title="Hi")
    with pytest.raises(ValueError, match="no 'Nope' layout"):
        deck.apply_theme("Basic White", layouts={"Title": "Nope"})
    with pytest.raises(ValueError, match="no bundled theme"):
        deck.apply_theme("Nope")
    assert deck.theme == "Basic White" and deck[0].title == "Hi"


def test_theme_setter(tmp_path):
    deck = from_markdown("# One\n\n- a\n- b\n")
    theme = other_theme("Basic White")
    deck.theme = theme
    assert deck.theme == theme
    assert reopen(deck, tmp_path)[0].body == "a\nb"
