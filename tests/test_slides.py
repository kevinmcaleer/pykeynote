from pathlib import Path

import pytest

from pykeynote import Paragraph, Presentation, from_markdown, parse_markdown, themes

FIXTURES = Path(__file__).parent / "fixtures"


def reopen(deck, tmp_path, name="out.key"):
    out = tmp_path / name
    deck.save(out)
    return Presentation.open(out)


def check_consistent(deck):
    """Every slide node, slide and component the show refers to exists, and nothing dangles."""
    p = deck.package
    show = p.get(deck._show_id)
    show_refs = set(p.segment(deck._show_id).header.message_infos[0].object_references)
    components = {c.identifier: c for c in p.metadata.components}
    for ref in show.slideTree.slides:
        assert ref.identifier in show_refs
        node = p.get(ref.identifier)
        slide_id = node.slide.identifier
        assert slide_id in p
        assert slide_id in components, "slide has no component"
        c = components[slide_id]
        assert p.file_of(slide_id) == f"Index/{c.locator or c.preferred_locator}.iwa"
    for c in components.values():
        for e in c.external_references:
            assert e.component_identifier in components or e.component_identifier == 0
    files = {f"Index/{c.locator or c.preferred_locator}.iwa" for c in components.values()}
    assert {n for n in p.filenames if n.startswith("Index/")} <= files | {"Index/Metadata.iwa"}
    ids = [i for i, _ in p.objects()]
    assert len(ids) == len(set(ids))
    assert max(ids) <= p.metadata.last_object_identifier


@pytest.fixture
def deck():
    return Presentation.open(FIXTURES / "layouts-basic-white.key")


def test_move_slide(deck, tmp_path):
    before = [s.layout for s in deck]
    deck.move_slide(3, 0)
    again = reopen(deck, tmp_path)
    assert [s.layout for s in again] == [before[3]] + before[:3] + before[4:]
    check_consistent(again)


def test_delete_slide(deck, tmp_path):
    before = [s.layout for s in deck]
    deck.delete_slide(3)
    deck.delete_slide(-1)
    again = reopen(deck, tmp_path)
    assert [s.layout for s in again] == before[:3] + before[4:-1]
    assert not any("Slide" in n and n.endswith(".iwa") and n not in again.package.filenames
                   for n in again.package.filenames)
    check_consistent(again)


def test_delete_selected_slide_moves_selection(tmp_path):
    deck = Presentation.open(FIXTURES / "transitions-basic-white.key")
    deck.delete_slide(3)  # Keynote saved this file with the last slide selected
    again = reopen(deck, tmp_path)
    remaining = {r.identifier for r in again.package.get(again._show_id).slideTree.slides}
    for _, obj in again.package.objects("KN.SlideCollectionSelectionArchive"):
        assert {r.identifier for r in obj.slide_nodes} <= remaining


def test_cannot_delete_last_slide(tmp_path):
    deck = Presentation.open(FIXTURES / "blank-basic-white.key")
    with pytest.raises(ValueError):
        deck.delete_slide(0)


def test_duplicate_slide(deck, tmp_path):
    copy = deck.duplicate_slide(3)
    copy.title = "The copy"
    again = reopen(deck, tmp_path)
    assert len(again) == 18
    assert again[3].title == "Title & Bullets"
    assert again[4].title == "The copy"
    assert again[4].body == again[3].body
    assert again[4].layout == "Title & Bullets"
    check_consistent(again)


def test_duplicate_then_delete_original(deck, tmp_path):
    deck.duplicate_slide(3, to=0)
    deck.delete_slide(4)
    again = reopen(deck, tmp_path)
    assert again[0].layout == "Title & Bullets"
    assert [s.layout for s in again].count("Title & Bullets") == 1
    check_consistent(again)


def test_new_presentation(tmp_path):
    assert "Basic White" in themes()
    deck = Presentation.new()
    assert len(deck) == 0
    deck.add_slide("Title", title="Robots!", body="Kevin McAleer")
    deck.add_slide("Title & Bullets", title="Why robots?",
                   body=[Paragraph("Fun"), Paragraph("Mostly", 1), "Useful"], notes="Short one")
    deck.add_slide("Blank")
    again = reopen(deck, tmp_path)
    assert [s.layout for s in again] == ["Title", "Title & Bullets", "Blank"]
    assert again[0].title == "Robots!" and again[0].body == "Kevin McAleer"
    assert [(p.text, p.level) for p in again[1].paragraphs] == [("Fun", 0), ("Mostly", 1), ("Useful", 0)]
    assert again[1].notes == "Short one"
    assert again[2].notes == ""
    check_consistent(again)


def test_new_presentation_keeps_working_after_save(tmp_path):
    deck = Presentation.new()
    deck.add_slide("Title Only", title="One")
    deck.save(tmp_path / "a.key")
    deck.add_slide("Title Only", title="Two")
    again = reopen(deck, tmp_path, "b.key")
    assert [s.title for s in again] == ["One", "Two"]


def test_new_presentation_needs_a_slide(tmp_path):
    with pytest.raises(ValueError):
        Presentation.new().save(tmp_path / "empty.key")


def test_add_slide_errors(deck):
    with pytest.raises(ValueError, match="no slide uses"):
        deck.add_slide("Nonexistent")
    with pytest.raises(ValueError, match="doesn't show a title"):
        deck.add_slide("Bullets", title="No title here")


def test_add_slide_at_index(deck, tmp_path):
    deck.add_slide("Section", title="Part two", index=1)
    again = reopen(deck, tmp_path)
    assert again[1].title == "Part two"
    assert again[1].layout == "Section"


def test_transitions_and_skip(tmp_path):
    deck = Presentation.open(FIXTURES / "transitions-basic-white.key")
    deck[3].set_transition("magic move", 2)
    deck[0].set_transition(None)
    deck[1].skipped = True
    again = reopen(deck, tmp_path)
    assert [(s.transition.effect, s.transition.duration, s.skipped) for s in again] == [
        (None, 1.5, False), ("push", 1.5, True), ("magic move", 1.5, False), ("magic move", 2.0, False)
    ]
    assert again[3].transition.effect_id == "apple:magic-move-implied-motion-path"


def test_markdown_round_trip(tmp_path):
    for name in ("layouts-basic-white.key", "transitions-basic-white.key"):
        md = Presentation.open(FIXTURES / name).to_markdown()
        again = reopen(from_markdown(md), tmp_path, name)
        assert again.to_markdown() == md
        check_consistent(again)


def test_markdown_without_layouts(tmp_path):
    md = """# Robots!

Kevin McAleer

---

# Why robots?

- Fun
  - Mostly
- Useful

???
Keep it short.

---

<!-- transition: dissolve 1s -->
<!-- skipped -->
# Thanks

---

- Just bullets
"""
    again = reopen(from_markdown(md), tmp_path)
    assert [s.layout for s in again] == ["Title", "Title & Bullets", "Title Only", "Bullets"]
    assert again[1].notes == "Keep it short."
    assert [(p.text, p.level) for p in again[1].paragraphs] == [("Fun", 0), ("Mostly", 1), ("Useful", 0)]
    assert again[2].transition.effect == "dissolve" and again[2].transition.duration == 1.0
    assert again[2].skipped


def test_parse_markdown_details():
    specs = parse_markdown("""<!-- layout: Quote -->
A long
quote over lines

\\# not a heading

---

```
---
```
""")
    assert len(specs) == 2
    assert specs[0].layout == "Quote"
    assert [p.text for p in specs[0].paragraphs] == ["A long quote over lines", "# not a heading"]


@pytest.mark.parametrize("aspect, size", [("16:9", (1920, 1080)), ("4:3", (1024, 768))])
def test_new_presentation_aspect(tmp_path, aspect, size):
    deck = Presentation.new(aspect=aspect)
    deck.add_slide("Title & Bullets", title="Shape", body="One\nTwo")
    again = reopen(deck, tmp_path)
    assert again.size == size
    assert again[0].title == "Shape"
    check_consistent(again)


def test_new_presentation_defaults_to_widescreen():
    assert Presentation.new().size == (1920, 1080)
    assert from_markdown("# Hi").size == (1920, 1080)
    assert from_markdown("# Hi", aspect="4:3").size == (1024, 768)


def test_new_presentation_bad_aspect():
    with pytest.raises(ValueError, match="aspect"):
        Presentation.new(aspect="21:9")


def test_widescreen_markdown_round_trip(tmp_path):
    md = Presentation.open(FIXTURES / "layouts-basic-white-wide.key").to_markdown()
    again = reopen(from_markdown(md), tmp_path)
    assert again.to_markdown() == md
