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


# --- images, shapes, tables and charts ---------------------------------------------


def test_objects(deck, tmp_path):
    from test_media import png
    from test_slides import check_consistent

    picture = tmp_path / "red.png"
    picture.write_bytes(png(40, 20))
    blue = tmp_path / "blue.png"
    blue.write_bytes(png(40, 20, (0, 0, 200)))

    s = tools.add_shape(deck, 1, "star", text="Wow", fill="#ff0000", x=100, y=100, width=200, height=200)
    star = s["drawables"][-1]
    assert (star["type"], star["text"], star["fill"], star["x"]) == ("star", "Wow", "#ff0000", 100)

    s = tools.add_text_box(deck, 1, ["One", {"text": "Two", "level": 1}])
    assert s["drawables"][-1]["type"] == "text box"

    s = tools.add_table(deck, 1, [["Name", "Score"], ["Ada", 3], ["Bob", None]], name="Scores")
    table = s["drawables"][-1]
    assert table["rows"] == [["Name", "Score"], ["Ada", 3], ["Bob", None]] and table["name"] == "Scores"

    s = tools.add_chart(deck, 1, "column", [[1, 2], [3, 4]], ["2025", "2026"], ["Q1", "Q2"], legend=True)
    chart = s["drawables"][-1]
    assert chart["chart_type"] == "column" and chart["data"] == [[1, 2], [3, 4]]

    s = tools.add_image(deck, 1, str(picture), x=10, y=10, width=400, description="red")
    image = s["images"][-1]
    assert image["size"] == [400, 200] and image["description"] == "red"
    s = tools.replace_image(deck, 1, image["id"], str(blue))
    assert len(s["images"]) == 1

    s = tools.add_build(deck, 1, chart["id"])
    assert s["builds"][-1]["target"] == chart["id"]
    with pytest.raises(ValueError, match="builds first"):
        tools.delete_drawable(deck, 1, chart["id"])
    tools.clear_builds(deck, 1)

    s = tools.delete_drawable(deck, 1, star["id"])
    assert star["id"] not in [d["id"] for d in s["drawables"]]
    s = tools.remove_image(deck, 1, s["images"][-1]["id"])
    assert s["images"] == []
    check_consistent(Presentation.open(deck))

    with pytest.raises(ValueError, match="both x and y"):
        tools.add_shape(deck, 1, x=10)
    with pytest.raises(ValueError, match="no shape"):
        tools.delete_drawable(deck, 1, 999999)
    json.dumps(tools.read_slide(deck, 1))


def test_cli_objects(tmp_path, capsys):
    from test_media import png

    key = tmp_path / "talk.key"
    run(capsys, "new", key)
    picture = tmp_path / "red.png"
    picture.write_bytes(png(40, 20))
    data = tmp_path / "sales.csv"
    data.write_text(",Q1,Q2\n2025,1,2\n2026,3,4\n", encoding="utf-8")

    for argv in (["shape", key, 0, "--kind", "oval", "--text", "Hi", "--fill", "blue"],
                 ["textbox", key, 0, "Note", "  detail", "--x", "50", "--y", "50"],
                 ["table", key, 0, "--row", "A,B", "--row", "1,true"],
                 ["chart", key, 0, "line", "--csv", data, "--legend", "no"],
                 ["image", key, 0, picture, "--width", "100", "--alt", "red"]):
        assert run(capsys, *argv)[0] == 0, argv

    code, out, _ = run(capsys, "show", key, 0, "--json")
    s = json.loads(out)
    added = s["drawables"][-4:]  # the title slide already has a text box for the author
    assert [d["type"] for d in added] == ["oval", "text box", "table", "chart"]
    assert added[1]["text"] == "Note\ndetail"
    assert added[2]["rows"] == [["A", "B"], [1, True]]
    assert added[3]["row_names"] == ["2025", "2026"]
    assert added[3]["column_names"] == ["Q1", "Q2"]

    code, out, _ = run(capsys, "show", key, 0)
    assert "chart (id" in out and "image (id" in out

    chart_id = added[3]["id"]
    assert run(capsys, "build", key, 0, "--target", chart_id)[0] == 0
    assert Presentation.open(key)[0].builds[-1].target == chart_id
    assert run(capsys, "build", key, 0, "--clear")[0] == 0
    assert run(capsys, "remove", key, 0, chart_id)[0] == 0
    assert run(capsys, "remove", key, 0, s["images"][0]["id"])[0] == 0
    s = Presentation.open(key)[0]
    assert len(s.charts) == 0 and s.images == []

    code, _, err = run(capsys, "table", key, 0)
    assert code == 1 and "--csv" in err


def test_cli_and_tools_movies(tmp_path, capsys):
    p = Presentation.open(Path(__file__).parent / "fixtures" / "media-video-audio.key").package
    clip, tone = tmp_path / "clip.mp4", tmp_path / "tone.m4a"
    clip.write_bytes(p.read_file("Data/clip-9072.mp4"))
    tone.write_bytes(p.read_file("Data/tone-9074.m4a"))
    key = tmp_path / "talk.key"
    run(capsys, "new", key)
    assert run(capsys, "movie", key, 0, clip, "--x", "10", "--y", "10", "--loop", "repeat", "--alt", "pattern")[0] == 0
    detail = tools.add_movie(str(key), 0, str(tone), volume=0.5)
    video, sound = detail["movies"]
    assert (video["audio_only"], video["description"], sound["audio_only"]) == (False, "pattern", True)

    code, out, _ = run(capsys, "show", key, 0)
    assert "video (id" in out and "sound (id" in out and "2.5s" in out
    assert run(capsys, "build", key, 0, "--target", video["id"])[0] == 0
    assert run(capsys, "remove", key, 0, video["id"])[0] == 0
    assert tools.remove_movie(str(key), 0, sound["id"])["movies"] == []
    s = Presentation.open(key)[0]
    assert s.movies == [] and s.builds == []
