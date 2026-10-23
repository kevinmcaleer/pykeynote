from pathlib import Path

import pytest

from pykeynote import Paragraph, Presentation, UnsupportedTextError
from pykeynote.text import PARAGRAPH, utf16_len

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def deck():
    return Presentation.open(FIXTURES / "layouts-basic-white.key")


def reopen(deck, tmp_path):
    out = tmp_path / "edited.key"
    deck.save(out)
    return Presentation.open(out)


def check_tables(text):
    """The invariants Keynote relies on: para styles line up with paragraph starts."""
    st = text._storage
    raw = text.raw
    chunks = raw.split(PARAGRAPH) if raw else [""]
    starts, offset = [], 0
    for c in chunks:
        starts.append(offset)
        offset += utf16_len(c) + 1
    assert [e.character_index for e in st.table_para_style.entries] == starts
    for name in ("table_para_data", "table_list_style", "table_para_starts", "table_para_bidi"):
        indexes = [e.character_index for e in getattr(st, name).entries]
        assert indexes[0] == 0
        assert set(indexes) <= set(starts), name


def test_set_title(deck, tmp_path):
    deck[3].title = "Robots are great 🤖"
    again = reopen(deck, tmp_path)
    assert again[3].title == "Robots are great 🤖"
    assert again[3].body == "First bullet\nSecond bullet\nThird bullet"
    assert again[4].body == deck[4].body  # other slides untouched
    check_tables(again[3].title_text)


def test_set_body_more_paragraphs_with_emoji(deck, tmp_path):
    deck[3].body = "🚀 One\nTwo\nThree\nFour\nFive"
    again = reopen(deck, tmp_path)
    paras = again[3].paragraphs
    assert [p.text for p in paras] == ["🚀 One", "Two", "Three", "Four", "Five"]
    assert all(p.bulleted for p in paras)
    check_tables(again[3].body_text)


def test_set_body_fewer_paragraphs(deck, tmp_path):
    deck[3].body = "Only one"
    again = reopen(deck, tmp_path)
    assert again[3].paragraphs == [Paragraph("Only one", 0, True)]
    check_tables(again[3].body_text)


def test_indent_levels(deck, tmp_path):
    deck[3].body = [Paragraph("Top", 0), Paragraph("Nested", 1), Paragraph("Deeper", 2), "Inherits"]
    again = reopen(deck, tmp_path)
    assert [(p.text, p.level) for p in again[3].paragraphs] == [
        ("Top", 0), ("Nested", 1), ("Deeper", 2), ("Inherits", 0)
    ]
    check_tables(again[3].body_text)


def test_line_break_inside_paragraph(deck, tmp_path):
    deck[3].body = [Paragraph("Line one\nline two")]
    again = reopen(deck, tmp_path)
    assert again[3].paragraphs[0].text == "Line one\nline two"
    assert len(again[3].paragraphs) == 1


def test_empty_body(deck, tmp_path):
    deck[3].body = ""
    again = reopen(deck, tmp_path)
    assert again[3].body == ""
    assert again[3].paragraphs == []
    check_tables(again[3].body_text)


def test_fill_an_empty_placeholder(tmp_path):
    deck = Presentation.open(FIXTURES / "transitions-basic-white.key")
    assert deck[0].body == ""
    deck[0].body = "Now\nwith\nbullets"
    again = reopen(deck, tmp_path)
    assert again[0].body == "Now\nwith\nbullets"
    check_tables(again[0].body_text)


def test_notes(deck, tmp_path):
    deck[0].notes = "Say hello\nThen start"
    again = reopen(deck, tmp_path)
    assert again[0].notes == "Say hello\nThen start"


def test_hidden_placeholder_refuses(deck):
    with pytest.raises(ValueError, match="doesn't show a title"):
        deck[4].title = "Bullets has no title"


def test_bad_characters_refused(deck):
    with pytest.raises(ValueError):
        deck[3].body = [Paragraph("a\rb")]


def test_anchored_objects_refused(deck):
    text = deck[3].body_text
    entry = text._storage.table_attachment.entries.add()
    entry.character_index = 0
    with pytest.raises(UnsupportedTextError):
        text.set_paragraphs(["x"])


def test_only_changed_files_are_rewritten(deck, tmp_path):
    deck[3].title = "Changed"
    again = reopen(deck, tmp_path)
    original = Presentation.open(FIXTURES / "layouts-basic-white.key")
    changed = [n for n in original.package.filenames
               if original.package.read_file(n) != again.package.read_file(n)]
    slide_file = original.package.file_of(original[3]._slide_id)
    assert slide_file in changed
    assert set(changed) <= {slide_file, "Index/Document.iwa"}


def test_save_in_place(tmp_path):
    path = tmp_path / "deck.key"
    path.write_bytes((FIXTURES / "transitions-basic-white.key").read_bytes())
    deck = Presentation.open(path)
    deck[1].title = "Pushed"
    deck.save()
    assert Presentation.open(path)[1].title == "Pushed"
