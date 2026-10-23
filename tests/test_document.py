from pathlib import Path

import pytest

from pykeynote import Paragraph, Presentation

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def layouts():
    return Presentation.open(FIXTURES / "layouts-basic-white.key")


@pytest.fixture(scope="module")
def transitions():
    return Presentation.open(FIXTURES / "transitions-basic-white.key")


BASIC_WHITE_LAYOUTS = [
    "Title", "Title & Photo", "Title & Photo Alt", "Title & Bullets", "Bullets",
    "Title, Bullets & Photo", "Title, Bullets & Live Video Small",
    "Title, Bullets & Live Video Large", "Section", "Title Only", "Agenda",
    "Statement", "Big Fact", "Quote", "Photo - 3 Up", "Photo", "Blank",
]


def test_presentation_basics(layouts):
    assert len(layouts) == 17
    assert layouts.theme == "Basic White"
    assert layouts.layouts == BASIC_WHITE_LAYOUTS
    assert layouts.size == (1024, 768)


def test_slide_layouts_in_order(layouts):
    assert [s.layout for s in layouts] == BASIC_WHITE_LAYOUTS


def test_title_shown_only_where_layout_has_one(layouts):
    titles = {s.layout: s.title for s in layouts}
    assert titles["Title & Bullets"] == "Title & Bullets"
    assert titles["Section"] == "Section"
    for layout in ("Bullets", "Statement", "Quote", "Blank", "Photo"):
        assert titles[layout] is None


def test_body_and_bullets(layouts):
    slide = layouts[3]
    assert slide.body == "First bullet\nSecond bullet\nThird bullet"
    assert slide.paragraphs == [
        Paragraph("First bullet", 0, True),
        Paragraph("Second bullet", 0, True),
        Paragraph("Third bullet", 0, True),
    ]
    statement = layouts[11]
    assert statement.layout == "Statement"
    assert not any(p.bulleted for p in statement.paragraphs)
    assert layouts[8].body is None  # Section has no body


def test_notes(layouts):
    assert [s.notes for s in layouts] == [f"Notes for {name}" for name in BASIC_WHITE_LAYOUTS]


def test_transitions(transitions):
    got = [(s.title, s.transition.effect, s.transition.duration) for s in transitions]
    assert got == [
        ("Dissolve", "dissolve", 1.5),
        ("Push", "push", 1.5),
        ("Magic Move", "magic move", 1.5),
        ("None", None, 1.0),
    ]
    assert transitions[0].transition.effect_id == "apple:dissolve"


@pytest.mark.parametrize("name, theme, layouts_count", [
    ("blank-basic-white.key", "Basic White", 17),
    ("blank-basic-black.key", "Basic Black", 17),
    ("blank-white.key", "White", 14),
])
def test_blank_decks(name, theme, layouts_count):
    deck = Presentation.open(FIXTURES / name)
    assert len(deck) == 1
    assert deck.theme == theme
    assert len(deck.layouts) == layouts_count


def test_unchanged_save_is_identical(tmp_path, transitions):
    out = tmp_path / "copy.key"
    transitions.save(out)
    again = Presentation.open(out)
    assert [s.to_dict() for s in again] == [s.to_dict() for s in transitions]
    assert again.package.filenames == transitions.package.filenames
    for name in again.package.filenames:
        assert again.package.read_file(name) == transitions.package.read_file(name)


def test_to_dict(layouts):
    d = layouts[3].to_dict()
    assert [x["type"] for x in d.pop("drawables")] == ["text box"]
    assert d == {
        "index": 3,
        "layout": "Title & Bullets",
        "title": "Title & Bullets",
        "body": "First bullet\nSecond bullet\nThird bullet",
        "notes": "Notes for Title & Bullets",
        "skipped": False,
        "transition": {"effect": None, "duration": 1.0, "delay": 0.5, "automatic": False},
        "images": [],
    }
