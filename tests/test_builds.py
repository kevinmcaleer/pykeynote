from pathlib import Path

import pytest

from pykeynote import Build, Presentation, from_markdown

from test_slides import check_consistent, reopen

FIXTURES = Path(__file__).parent / "fixtures"


def test_read_builds_from_keynote_file():
    deck = Presentation.open(FIXTURES / "builds-talk.key")
    body, shape = deck[0].builds
    assert body == Build("body", "in", "dissolve", "By Paragraph", 1.0, 3, "apple:dissolve character")
    assert isinstance(shape.target, int)
    assert (shape.effect, shape.delivery, shape.steps) == ("move in", "All at Once", 1)
    assert deck[1].builds == []


def test_add_builds(tmp_path):
    deck = Presentation.new()
    slide = deck.add_slide("Title & Bullets", title="Builds", body="One\nTwo\n\nThree")
    slide.add_build("title", "move in", duration=0.5)
    slide.add_build("body", "dissolve")
    again = reopen(deck, tmp_path)
    title, body = again[0].builds
    assert (title.target, title.effect, title.delivery, title.duration, title.steps) == (
        "title", "move in", "All at Once", 0.5, 1)
    assert (body.target, body.effect, body.delivery, body.steps) == ("body", "dissolve", "By Paragraph", 3)
    assert again[0]._node.build_event_count == 4
    check_consistent(again)


def test_builds_listed_in_play_order(tmp_path):
    # Keynote 14.5 reorders SlideArchive.builds on save but keeps the chunks in play order.
    deck = Presentation.new()
    slide = deck.add_slide("Title & Bullets", title="T", body="a\nb")
    slide.add_build("title", "move in")
    slide.add_build("body", "dissolve")
    refs = list(slide._slide.builds)
    del slide._slide.builds[:]
    for r in reversed(refs):
        slide._slide.builds.add().CopyFrom(r)
    assert [b.target for b in slide.builds] == ["title", "body"]


def test_build_all_at_once_and_out(tmp_path):
    deck = Presentation.new()
    slide = deck.add_slide("Title & Bullets", title="T", body="a\nb")
    slide.add_build("body", "dissolve", delivery="all at once", kind="out")
    b = reopen(deck, tmp_path)[0].builds[0]
    assert (b.kind, b.delivery, b.steps) == ("out", "All at Once", 1)


def test_build_errors():
    deck = Presentation.new()
    slide = deck.add_slide("Title Only", title="T")
    with pytest.raises(ValueError, match="doesn't show a body"):
        slide.add_build("body")
    with pytest.raises(ValueError, match="delivery"):
        slide.add_build("title", delivery="sideways")
    with pytest.raises(ValueError, match="kind"):
        slide.add_build("title", kind="sideways")


def test_clear_builds(tmp_path):
    deck = Presentation.open(FIXTURES / "builds-talk.key")
    deck[0].clear_builds()
    again = reopen(deck, tmp_path)
    assert again[0].builds == []
    assert again[0]._node.build_event_count == 0
    assert not list(again.package.objects("KN.BuildArchive"))
    check_consistent(again)


def test_duplicate_slide_copies_builds_with_new_ids(tmp_path):
    deck = Presentation.open(FIXTURES / "builds-talk.key")
    deck.duplicate_slide(0)
    again = reopen(deck, tmp_path)
    assert [len(s.builds) for s in again] == [2, 2, 0]
    uuids = {(c.build_id.lower, c.build_id.upper) for _, c in again.package.objects("KN.BuildChunkArchive")}
    assert len(uuids) == 4  # two builds per slide, none shared between the copies
    check_consistent(again)


def test_builds_in_markdown(tmp_path):
    md = Presentation.open(FIXTURES / "builds-talk.key").to_markdown()
    assert "<!-- build: body, dissolve, by bullet, 1s -->" in md
    again = reopen(from_markdown(md), tmp_path)
    assert again.to_markdown() == md


def test_markdown_build_options(tmp_path):
    deck = from_markdown("""<!-- build: title, move in, 0.5s -->
<!-- build: body, dissolve, all at once, out -->
# Hello

- a
- b
""")
    title, body = reopen(deck, tmp_path)[0].builds
    assert (title.effect, title.duration) == ("move in", 0.5)
    assert (body.delivery, body.kind) == ("All at Once", "out")
