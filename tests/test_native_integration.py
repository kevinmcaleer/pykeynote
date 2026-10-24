"""Checks that files written by pykeynote open in real Keynote and show the right text.

Needs macOS with Keynote and PYKEYNOTE_INTEGRATION=1.
"""

import os
import sys
from pathlib import Path

import pytest

from pykeynote import Paragraph, Presentation

from keynote_app import Document, KeynoteError

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
        deck = Document(path)
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


@pytest.mark.parametrize("aspect, size", [("16:9", (1920, 1080)), ("4:3", (1024, 768))])
def test_new_deck_size_in_keynote(tmp_path, open_in_keynote, aspect, size):
    from pykeynote import from_markdown

    out = tmp_path / f"deck-{aspect.replace(':', 'x')}.key"
    from_markdown(MARKDOWN, aspect=aspect).save(out)
    info = open_in_keynote(out).info()
    assert (info["width"], info["height"]) == size


def test_builds_survive_keynote(tmp_path, open_in_keynote):
    deck = Presentation.new()
    slide = deck.add_slide("Title & Bullets", title="Builds", body="One\nTwo\nThree")
    slide.add_build("title", "move in")
    slide.add_build("body", "dissolve")
    out = tmp_path / "builds.key"
    deck.save(out)

    live = open_in_keynote(out)
    resaved = tmp_path / "builds-resaved.key"
    live.save(resaved)
    builds = Presentation.open(resaved)[0].builds
    assert [(b.target, b.effect, b.delivery, b.steps) for b in builds] == [
        ("title", "move in", "All at Once", 1),
        ("body", "dissolve", "By Paragraph", 3),
    ]


def test_broll_style_survives_keynote(tmp_path, open_in_keynote):
    # Title Wipe on click, subtitle Wipe after it with a delay, bullets Fade and Move, Wipe transition.
    deck = Presentation.new()
    s = deck.add_slide("Title & Bullets", title="test", body=["some text", "more points", "last bits"])
    s.add_subtitle("sub title")
    s.set_transition("wipe", 0.75, direction="from right")
    s.add_build("title", "wipe", direction="from left")
    s.add_build("subtitle", "wipe", direction="from top", start="after previous", delay=0.1)
    s.add_build("body", "fade and move", delivery="by bullet", duration=0.3)
    deck.add_slide("Title Only", title="next")
    out = tmp_path / "style.key"
    deck.save(out)
    before = deck[0].to_dict()

    live = open_in_keynote(out)
    resaved = tmp_path / "style-resaved.key"
    live.save(resaved)
    after = Presentation.open(resaved)[0].to_dict()
    assert after["subtitle"] == "sub title"
    assert after["transition"] == before["transition"]
    assert after["builds"] == before["builds"]


def test_images_survive_keynote(tmp_path, open_in_keynote):
    from test_media import png

    deck = Presentation.new()
    photo = deck.add_slide("Title & Photo", title="Placeholder photo")
    photo.add_image(png(1600, 900), description="A red picture")
    free = deck.add_slide("Blank")
    free.add_image(png(800, 800, (0, 0, 200)), position=(100, 100), size=(400, None), description="A blue square")
    three = deck.add_slide("Photo - 3 Up")
    three.add_image(png(300, 200, (0, 160, 0)))
    three.remove_image("Media-2")
    out = tmp_path / "images.key"
    deck.save(out)

    live = open_in_keynote(out)
    assert len(live) == 3
    resaved = tmp_path / "images-resaved.key"
    live.save(resaved)
    again = Presentation.open(resaved)
    (placeholder,) = again[0].images
    assert (placeholder.placeholder, placeholder.pixel_size, placeholder.description) == ("Media", (1600, 900), "A red picture")
    assert placeholder.data == png(1600, 900)
    (square,) = again[1].images
    assert square.position == pytest.approx((100, 100)) and square.size == pytest.approx((400, 400))
    assert square.description == "A blue square"
    assert sorted((i.placeholder, i.is_sample) for i in again[2].images) == [("Media", False), ("Media-1", True)]


@pytest.mark.parametrize("aspect", ["16:9", "4:3"])
def test_every_theme_opens_in_keynote(tmp_path, open_in_keynote, aspect):
    from pykeynote import from_markdown, themes

    for theme in themes():
        out = tmp_path / f"{theme}-{aspect.replace(':', 'x')}.key"
        from_markdown(MARKDOWN, theme=theme, aspect=aspect).save(out)
        live = open_in_keynote(out)
        assert [s["title"] for s in live.read_slides()][:2] == ["Robots!", "Why robots?"]


def test_switched_theme_opens_in_keynote(tmp_path, open_in_keynote):
    from pykeynote import themes

    deck = Presentation.open(FIXTURES / "builds-talk.key")
    theme = next(t for t in themes() if t != deck.theme)
    deck.apply_theme(theme)
    out = tmp_path / "switched.key"
    deck.save(out)
    live = open_in_keynote(out)
    assert live.theme == theme
    assert [s["title"] for s in live.read_slides()] == ["Why robots? 🤖", "Robots!"]


def test_movies_survive_keynote(tmp_path, open_in_keynote):
    from test_media import png

    media = Presentation.open(FIXTURES / "media-video-audio.key").package
    clip, tone = media.read_file("Data/clip-9072.mp4"), media.read_file("Data/tone-9074.m4a")
    deck = Presentation.new()
    free = deck.add_slide("Blank")
    video = free.add_movie(clip, position=(200, 200), size=(640, None), description="A test pattern", loop="repeat")
    free.add_build(video, "dissolve")
    deck.add_slide("Blank").add_audio(tone, name="tone.m4a")
    deck.add_slide("Title & Photo", title="Video in placeholder").add_movie(clip, poster=png(640, 360))
    out = tmp_path / "movies.key"
    deck.save(out)

    live = open_in_keynote(out)
    assert len(live) == 3
    resaved = tmp_path / "movies-resaved.key"
    live.save(resaved)
    again = Presentation.open(resaved)
    (v,) = again[0].movies
    assert (v.position, v.size, v.loop, v.description) == ((200, 200), (640, 360), "repeat", "A test pattern")
    assert v.data == clip and again[0].builds[0].target == v.identifier
    (s,) = again[1].movies
    assert s.audio_only and s.data == tone
    (p,) = again[2].movies
    assert p.placeholder == "Media" and p.data == clip
