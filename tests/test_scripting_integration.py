"""Runs against real Keynote. Needs macOS and PYKEYNOTE_INTEGRATION=1."""

import os
import sys

import pytest

from pykeynote import KeynoteError
from pykeynote.scripting import Presentation, list_themes

pytestmark = [
    pytest.mark.keynote,
    pytest.mark.skipif(
        sys.platform != "darwin" or os.environ.get("PYKEYNOTE_INTEGRATION") != "1",
        reason="needs macOS with Keynote and PYKEYNOTE_INTEGRATION=1",
    ),
]


@pytest.fixture
def pres(tmp_path):
    p = Presentation.new(path=tmp_path / "test.key")
    yield p
    try:
        p.close()
    except KeynoteError:
        pass  # the test already closed it


def test_themes_listed():
    assert list_themes()


def test_new_presentation_saved(pres, tmp_path):
    assert os.path.exists(tmp_path / "test.key")
    assert len(pres) >= 1
    assert pres.layouts


def test_slide_text_round_trip(pres):
    layout = next((l for l in pres.layouts if "Bullets" in l), pres.layouts[0])
    s = pres.add_slide(layout, title="Hello", body="one\ntwo", notes="say hi")
    data = s.read()
    assert data["title"] == "Hello"
    assert data["body"] == "one\ntwo"
    assert data["notes"] == "say hi"
    assert data["layout"] == layout


def test_move_and_delete(pres):
    start = len(pres)
    s = pres.add_slide(title="Moved")
    s.move_to(0)
    assert pres[0].title == "Moved"
    pres[0].delete()
    assert len(pres) == start


def test_transition(pres):
    s = pres[0]
    s.set_transition("dissolve", duration=1.5)
    t = s.transition
    assert t.effect == "dissolve"
    assert t.duration == pytest.approx(1.5)


def test_change_theme(pres):
    themes = list_themes()
    other = next(t for t in themes if t != pres.theme)
    pres.theme = other
    assert pres.theme == other


def test_reopen_saved_file(pres, tmp_path):
    pres[0].update(title="Persisted")
    pres.save()
    pres.close()
    again = Presentation.open(tmp_path / "test.key")
    try:
        assert again[0].title == "Persisted"
    finally:
        again.close()
