import pytest

from pykeynote import KeynoteError, _osa
from pykeynote.scripting import Presentation, Transition, list_themes
from pykeynote.transitions import normalize_effect


def info(count=3, **extra):
    data = {"name": "Deck", "path": "/tmp/Deck.key", "theme": "Basic White",
            "width": 1920, "height": 1080, "layouts": ["Title", "Title & Bullets"],
            "slide_count": count}
    data.update(extra)
    return data


def test_list_themes(osa):
    osa.reply(["Basic White", "Basic Black"])
    assert list_themes() == ["Basic White", "Basic Black"]


def test_new_saves_with_key_extension(osa, tmp_path):
    osa.reply("DOC1")
    Presentation.new(theme="Basic Black", path=tmp_path / "talk")
    (_, _, new_args), (_, _, save_args) = osa.calls
    assert new_args["theme"] == "Basic Black"
    assert save_args == {"doc": "DOC1", "path": str(tmp_path / "talk.key")}


def test_open_missing_file(osa, tmp_path):
    with pytest.raises(FileNotFoundError):
        Presentation.open(tmp_path / "nope.key")
    assert osa.calls == []


def test_open_passes_absolute_path(osa, tmp_path):
    f = tmp_path / "a.key"
    f.write_text("")
    osa.reply("DOC1")
    assert Presentation.open(f).id == "DOC1"
    assert osa.last[2] == {"path": str(f)}


def test_text_is_passed_as_data_not_code(osa):
    pres = Presentation("DOC1")
    nasty = 'He said "hi"\n"); Application("Finder").delete(); ("'
    osa.reply(info())
    pres[0].title = nasty
    language, script, args = osa.last
    assert args == {"doc": "DOC1", "index": 0, "title": nasty}
    assert nasty not in script


def test_update_rejects_unknown_fields(osa):
    with pytest.raises(TypeError):
        Presentation("DOC1").add_slide(colour="red")


def test_negative_index_and_range(osa):
    pres = Presentation("DOC1")
    osa.reply(info(count=3))
    assert pres[-1].index == 2
    osa.reply(info(count=3))
    with pytest.raises(IndexError):
        pres[3]


def test_add_slide_with_fields_and_index(osa):
    pres = Presentation("DOC1")
    osa.reply("4", language="AppleScript")  # count after adding
    osa.reply(None)                         # update
    osa.reply(info(count=4))                # len() inside move_to
    slide = pres.add_slide("Title & Bullets", index=0, title="Hello", body="a\nb")
    add, update, _, move = osa.calls
    assert add[2] == ["DOC1", "Title & Bullets"]
    assert update[2] == {"doc": "DOC1", "index": 3, "title": "Hello", "body": "a\nb"}
    assert move[0] == "AppleScript" and move[2] == ["DOC1", "4", "1"]
    assert slide.index == 0


def test_read_slides(osa):
    rows = [{"index": 0, "title": "T", "body": None, "notes": "", "layout": "Title",
             "skipped": False, "transition": {"effect": "magic move", "duration": 1,
                                              "delay": 0, "automatic": False}}]
    osa.reply(rows)
    assert Presentation("DOC1").read_slides() == rows


def test_transition_round_trip(osa):
    pres = Presentation("DOC1")
    osa.reply(info())
    s = pres[1]
    osa.reply({"transition": {"effect": "magicMove", "duration": 1.5, "delay": 0.0, "automatic": True}})
    assert s.transition == Transition("magic move", 1.5, 0.0, True)
    s.set_transition("Dissolve", duration=2)
    language, script, args = osa.last
    assert language == "AppleScript"
    assert "{transition effect:dissolve}" in script
    assert args == ["DOC1", "2", "2.0", "", ""]


def test_bad_transition_effect_never_reaches_script(osa):
    pres = Presentation("DOC1")
    osa.reply(info())
    s = pres[0]
    with pytest.raises(ValueError):
        s.set_transition('dissolve} \n do shell script "rm -rf ~" --')
    assert len(osa.calls) == 1


@pytest.mark.parametrize("raw", ["none", "no transition effect", "noTransitionEffect"])
def test_normalize_no_effect(raw):
    assert normalize_effect(raw) == "no transition effect"


def test_osascript_errors_raise(monkeypatch):
    class Proc:
        returncode = 1
        stderr = "execution error: Error: Can't get object. (-1728)\n"
        stdout = ""

    monkeypatch.setattr(_osa.subprocess, "run", lambda *a, **k: Proc())
    with pytest.raises(KeynoteError, match="-1728"):
        list_themes()
