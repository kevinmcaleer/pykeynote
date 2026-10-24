"""Build start, delay and direction, transition direction, subtitles and apply_style."""

import pytest

from pykeynote import Presentation, from_markdown
from pykeynote.cli import main as cli_main

from test_slides import check_consistent, reopen


def style_check_deck():
    deck = Presentation.new()
    s = deck.add_slide("Title & Bullets", title="test", body=["some text", "more points", "last bits"])
    s.add_subtitle("sub title")
    s.set_transition("wipe", 0.75)
    s.add_build("title", "wipe", direction="from left")
    s.add_build("subtitle", "wipe", direction="from left", start="after previous", delay=0.1)
    s.add_build("body", "fade and move", delivery="by bullet", duration=0.3)
    return deck


def test_style_check_reads_back(tmp_path):
    again = reopen(style_check_deck(), tmp_path)
    s = again[0]
    assert s.subtitle == "sub title"
    t = s.transition
    assert (t.effect, t.effect_id, t.duration, t.direction) == ("wipe", "apple:wipe", 0.75, "from left")
    got = [(b.target, b.effect_id, b.delivery, b.duration, b.steps, b.start, b.delay, b.direction) for b in s.builds]
    assert got == [
        ("title", "apple:wipe", "All at Once", 1.0, 1, "on click", 0.0, "from left"),
        ("subtitle", "apple:wipe", "All at Once", 1.0, 1, "after previous", 0.1, "from left"),
        ("body", "apple:fade and move character", "By Paragraph", 0.3, 3, "on click", 0.0, None),
    ]
    check_consistent(again)


def test_written_fields_match_keynote(tmp_path):
    s = reopen(style_check_deck(), tmp_path)[0]
    p = s._package
    builds = {p.deref(r).drawable.identifier: p.deref(r).attributes for r in s._slide.builds}
    wipe = builds[s._slide.titlePlaceholder.identifier]
    # Keynote leaves Wipe's default direction out and writes no delivery options for it.
    assert not wipe.animationAttributes.HasField("direction")
    assert not wipe.HasField("custom_textDelivery") and not wipe.HasField("custom_deliveryOption")
    fade = builds[s._slide.bodyPlaceholder.identifier]
    assert fade.custom_deliveryOption == fade.kDeliveryOptionBackward
    assert fade.custom_travel_distance == 1.0
    assert not fade.HasField("custom_bounce")
    chunks = [p.deref(r) for r in s._slide.buildChunks]
    assert [(c.automatic, round(c.delay, 6)) for c in chunks] == [
        (False, 0.0), (True, 0.1), (False, 0.0), (False, 0.0), (False, 0.0)
    ]


@pytest.mark.parametrize("name, value", [("from right", 12), ("from top", 13), ("from bottom", 14),
                                         ("right to left", 12), ("from-bottom", 14)])
def test_directions(tmp_path, name, value):
    deck = Presentation.new()
    s = deck.add_slide("Title & Bullets", title="T", body="a")
    s.set_transition("wipe", 0.75, direction=name)
    s.add_build("title", "wipe", direction=name)
    s.add_build("body", "fade and move", direction=name)
    s = reopen(deck, tmp_path)[0]
    assert s._slide.transition.attributes.animationAttributes.direction == value
    assert s.transition.direction == s.builds[0].direction == s.builds[1].direction
    assert s.builds[0].direction.startswith("from ")


def test_direction_errors():
    deck = Presentation.new()
    s = deck.add_slide("Title & Bullets", title="T", body="a")
    with pytest.raises(ValueError, match="'dissolve' build has no direction"):
        s.add_build("title", "dissolve", direction="from left")
    with pytest.raises(ValueError, match="'dissolve' transition has no direction"):
        s.set_transition("dissolve", direction="from left")
    with pytest.raises(ValueError, match="direction must be one of"):
        s.add_build("title", "wipe", direction="diagonally")
    with pytest.raises(ValueError, match="start must be one of"):
        s.add_build("title", "wipe", start="whenever")
    with pytest.raises(ValueError, match="no subtitle"):
        deck.add_slide("Section", title="S").add_build("subtitle", "wipe")


def test_effect_aliases():
    deck = Presentation.new()
    s = deck.add_slide("Title & Bullets", title="T", body="a")
    assert s.add_build("title", "Fade-and-Move").effect_id == "apple:fade and move character"
    assert s.add_build("body", "WIPE").effect_id == "apple:wipe"


def test_subtitle_fills_layout_box_or_adds_one(tmp_path):
    deck = Presentation.new()
    bullets = deck.add_slide("Title & Bullets", title="T", body="a")
    assert bullets.subtitle is None  # the layout's subtitle box starts empty
    count = len(bullets.drawables)
    bullets.add_subtitle("sub")
    assert len(bullets.drawables) == count
    section = deck.add_slide("Section", title="S")
    box = section.add_subtitle("added")
    assert box.is_subtitle and box.position[0] == pytest.approx(95.0, abs=0.01)
    with pytest.raises(ValueError, match="already has a subtitle"):
        section.add_subtitle("again")
    with pytest.raises(ValueError, match="doesn't show a title"):
        deck.add_slide("Blank").add_subtitle("x")
    again = reopen(deck, tmp_path)
    assert [s.subtitle for s in again] == ["sub", "added", None]
    check_consistent(again)


def test_markdown_round_trip(tmp_path):
    md = style_check_deck().to_markdown()
    assert "<!-- transition: wipe 0.75s from left -->" in md
    assert "<!-- build: subtitle, wipe, all at once, 1s, after previous, delay 0.1s, from left -->" in md
    assert "# test\n## sub title\n" in md
    again = reopen(from_markdown(md), tmp_path)
    assert again.to_markdown() == md


def test_markdown_in_any_order(tmp_path):
    deck = from_markdown("""<!-- transition: wipe 0.75s from-right -->
<!-- build: title, wipe, 1s, from left -->
<!-- build: subtitle, wipe, 1s, after-previous, delay 0.1s -->
<!-- build: body, fade and move, by bullet, 0.3s -->
# test
## sub title

- a
- b
""")
    s = reopen(deck, tmp_path)[0]
    assert s.transition.direction == "from right"
    assert s.subtitle == "sub title"
    assert [(b.target, b.start, b.delay) for b in s.builds] == [
        ("title", "on click", 0.0), ("subtitle", "after previous", 0.1), ("body", "on click", 0.0)
    ]


def test_apply_style(tmp_path):
    deck = Presentation.new()
    deck.add_slide("Title", title="Hello")
    deck.add_slide("Title & Bullets", title="test", body=["a", "b"]).add_subtitle("sub")
    deck.add_slide("Blank")
    deck[1].add_build("title", "dissolve")
    deck.apply_style(
        transition={"effect": "wipe", "duration": 0.75},
        title_build={"effect": "wipe", "direction": "from left"},
        subtitle_build={"effect": "wipe", "start": "after previous", "delay": 0.1},
        body_build={"effect": "fade and move", "delivery": "by bullet", "duration": 0.3},
    )
    again = reopen(deck, tmp_path)
    assert [s.transition.effect for s in again] == ["wipe"] * 3
    assert [[b.target for b in s.builds] for s in again] == [["title"], ["title", "subtitle", "body"], []]
    check_consistent(again)


def test_apply_theme_keeps_style(tmp_path):
    deck = style_check_deck()
    before = deck[0].to_dict()["builds"]
    deck.apply_theme("Basic Black")
    s = reopen(deck, tmp_path)[0]
    assert s.subtitle == "sub title"
    assert s.to_dict()["builds"] == before


def test_cli(tmp_path, capsys):
    path = str(tmp_path / "cli.key")
    style_check_deck().save(path)
    assert cli_main(["edit", path, "0", "--transition", "wipe", "--duration", "0.75", "--direction", "from-top"]) == 0
    assert cli_main(["build", path, "0", "--target", "title", "--effect", "wipe", "--start", "after-previous",
                     "--delay", "0.2", "--direction", "from-bottom"]) == 0
    capsys.readouterr()
    assert cli_main(["show", path, "0"]) == 0
    out = capsys.readouterr().out
    assert "subtitle: sub title" in out
    assert "transition: wipe 0.75s from top" in out
    assert "build: title in, wipe, All at Once, 1s, after previous, delay 0.2s, from bottom" in out
