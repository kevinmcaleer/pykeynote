import json
from pathlib import Path

import pytest

from pykeynote import Presentation, themes, tools
from pykeynote.cli import main

MARKDOWN = """# Robots!

Kevin

---

<!-- transition: dissolve 1.5s -->
# Why robots?

- Fun
  - Mostly
- Useful

???
Keep it short.
"""


@pytest.fixture
def deck(tmp_path):
    path = str(tmp_path / "talk.key")
    tools.create_deck(path, MARKDOWN)
    return path


def test_create_and_read(deck):
    info = tools.deck_info(deck)
    assert info["theme"] == "Basic White"
    assert info["size"] == {"width": 1920, "height": 1080}
    assert [s["title"] for s in info["slides"]] == ["Robots!", "Why robots?"]
    assert "Title & Bullets" in info["layouts"]

    slide = tools.read_slide(deck, -1)
    assert slide["index"] == 1
    assert slide["paragraphs"] == [
        {"text": "Fun", "level": 0, "bulleted": True},
        {"text": "Mostly", "level": 1, "bulleted": True},
        {"text": "Useful", "level": 0, "bulleted": True},
    ]
    assert slide["notes"] == "Keep it short."
    assert slide["transition"]["effect"] == "dissolve"
    json.dumps(info), json.dumps(slide)  # JSON-ready


def test_create_without_markdown(tmp_path):
    path = tmp_path / "blank.key"
    info = tools.create_deck(str(path), aspect="4:3")
    assert info["size"] == {"width": 1024, "height": 768}
    assert info["slide_count"] == 1


def test_create_refuses_to_overwrite_and_non_key(deck, tmp_path):
    with pytest.raises(FileExistsError):
        tools.create_deck(deck)
    tools.create_deck(deck, "# Again", overwrite=True)
    assert tools.deck_info(deck)["slide_count"] == 1
    with pytest.raises(ValueError, match=r"\.key"):
        tools.create_deck(str(tmp_path / "talk.pptx"))


def test_edit_slide(deck):
    tools.edit_slide(deck, 1, title="Why? 🤖", body=["One", {"text": "Two", "level": 1}],
                     notes="New notes", skipped=True, transition="push", transition_duration=2)
    s = Presentation.open(deck)[1]
    assert s.title == "Why? 🤖"
    assert [(p.text, p.level) for p in s.paragraphs] == [("One", 0), ("Two", 1)]
    assert s.notes == "New notes"
    assert s.skipped
    assert (s.transition.effect, s.transition.duration) == ("push", 2)

    tools.edit_slide(deck, 1, body="a\nb", transition="none")
    s = Presentation.open(deck)[1]
    assert s.body == "a\nb"
    assert s.transition.effect is None


def test_edit_to_output_leaves_original(deck, tmp_path):
    out = str(tmp_path / "copy.key")
    tools.edit_slide(deck, 0, title="Changed", output=out)
    assert Presentation.open(deck)[0].title == "Robots!"
    assert Presentation.open(out)[0].title == "Changed"
    with pytest.raises(ValueError, match=r"\.key"):
        tools.edit_slide(deck, 0, title="x", output=str(tmp_path / "copy.pptx"))


def test_slide_list_changes(deck):
    added = tools.add_slide(deck, "Title & Bullets", title="Extra", body=["x"], index=1)
    assert added["index"] == 1
    assert [s["title"] for s in tools.deck_info(deck)["slides"]] == ["Robots!", "Extra", "Why robots?"]
    tools.move_slide(deck, 0, -1)
    tools.duplicate_slide(deck, 0)
    titles = [s["title"] for s in tools.deck_info(deck)["slides"]]
    assert titles == ["Extra", "Extra", "Why robots?", "Robots!"]
    result = tools.delete_slide(deck, 0)
    assert result["slide_count"] == 3


def test_builds(deck):
    s = tools.add_build(deck, 1, "body", "dissolve")
    assert s["builds"][0]["target"] == "body"
    assert s["builds"][0]["steps"] == 3
    assert tools.clear_builds(deck, 1)["builds"] == []


def test_apply_theme(deck, tmp_path):
    out = str(tmp_path / "black.key")
    theme = themes()[-1]  # whichever is bundled; the 4:3 switch is the visible change
    info = tools.apply_theme(deck, theme, aspect="4:3", output=out)
    assert info["theme"] == theme
    assert info["size"] == {"width": 1024, "height": 768}
    assert [s["title"] for s in info["slides"]] == ["Robots!", "Why robots?"]
    assert tools.deck_info(deck)["size"] == {"width": 1920, "height": 1080}


def test_export_markdown(deck, tmp_path):
    out = tmp_path / "talk.md"
    result = tools.export_markdown(deck, str(out))
    assert "# Why robots?" in result["markdown"]
    assert out.read_text(encoding="utf-8") == result["markdown"]


def test_errors(deck, tmp_path):
    with pytest.raises(FileNotFoundError):
        tools.deck_info(str(tmp_path / "missing.key"))
    with pytest.raises(IndexError):
        tools.read_slide(deck, 9)
    with pytest.raises(KeyError):
        tools.call("nope")


def test_tool_schemas_match_functions():
    import inspect

    for tool in tools.TOOLS:
        params = inspect.signature(tool["function"]).parameters
        schema = tool["inputSchema"]
        assert set(schema["properties"]) == set(params), tool["name"]
        required = {n for n, p in params.items() if p.default is inspect.Parameter.empty}
        assert set(schema["required"]) == required, tool["name"]


# --- the command line -----------------------------------------------------------


def run(capsys, *argv):
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out, err


def test_cli_round_trip(tmp_path, capsys):
    md = tmp_path / "talk.md"
    md.write_text(MARKDOWN, encoding="utf-8")
    key = tmp_path / "talk.key"
    code, out, _ = run(capsys, "new", key, "-m", md)
    assert code == 0 and "Why robots?" in out

    code, out, _ = run(capsys, "info", key, "--json")
    assert json.loads(out)["slide_count"] == 2

    code, out, _ = run(capsys, "edit", key, 1, "--title", "New", "--body", "A", "--body", "  B", "--skip", "yes")
    assert code == 0
    s = Presentation.open(key)[1]
    assert s.title == "New" and s.skipped
    assert [(p.text, p.level) for p in s.paragraphs] == [("A", 0), ("B", 1)]

    code, out, _ = run(capsys, "show", key, 1)
    assert "title: New" in out and "  - A" in out

    for argv in (["add", key, "--title", "End"], ["duplicate", key, 0], ["move", key, 0, -1],
                 ["delete", key, 0], ["build", key, 0, "--target", "title"]):
        assert run(capsys, *argv)[0] == 0, argv
    assert [s.title for s in Presentation.open(key)] == ["New", "End", "Robots!"]
    assert Presentation.open(key)[0].builds[0].target == "title"

    code, out, _ = run(capsys, "theme", key, "Basic White", "--aspect", "4:3", "--json")
    assert code == 0 and json.loads(out)["size"] == {"width": 1024, "height": 768}

    code, out, _ = run(capsys, "export", key)
    assert out.startswith("<!-- layout:")


def test_cli_errors(tmp_path, capsys):
    key = tmp_path / "talk.key"
    run(capsys, "new", key)
    code, _, err = run(capsys, "add", key, "--layout", "Quote")
    assert code == 1 and "no slide uses the 'Quote' layout" in err
    code, _, err = run(capsys, "info", tmp_path / "missing.key")
    assert code == 1 and "no such deck" in err
    code, out, _ = run(capsys, "info", tmp_path / "missing.key", "--json")
    assert code == 1 and json.loads(out)["type"] == "FileNotFoundError"


def test_cli_themes(capsys):
    code, out, _ = run(capsys, "themes")
    assert "Basic White" in out
