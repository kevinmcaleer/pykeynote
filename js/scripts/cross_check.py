"""The pykeynote half of scripts/cross-check.mjs.

    python cross_check.py DIR             # read keynotejs's js.key, then write py.key and py.json
    python cross_check.py DIR --edited    # read js-edited.key, pykeynote's deck as keynotejs edited it
"""

import json
import sys
from pathlib import Path

from pykeynote import Presentation


def scenario(picture: Path) -> Presentation:
    deck = Presentation.new("Basic White", "16:9")
    intro = deck.add_slide("Title & Bullets", title="Cross check", body="Written by one library\nRead by the other\n\nThird point")
    intro.notes = "Speaker notes"
    intro.add_build("title", effect="move in", duration=0.5)
    intro.add_build("body", "dissolve")

    shapes = deck.add_slide("Blank")
    star = shapes.add_shape("star", x=100, y=120, width=300, height=300, text="Star", fill="#3366ff")
    shapes.add_shape("rounded rectangle", x=500, y=120, width=400, height=200, style=2)
    shapes.add_text_box("Free text", x=100, y=600, width=600, height=80)
    shapes.add_build(star, effect="dissolve")

    table = deck.add_slide("Title Only", title="Scores")
    table.add_table([["Name", "Score", "Pass"], ["Ada", 42, True], ["Bob", 3.5, False], ["Cy", -7, None]], header_columns=1)

    charts = deck.add_slide("Blank")
    charts.add_chart("column", [[1, 2, 3], [4, 5, None]], ["2024", "2025"], ["Q1", "Q2", "Q3"], x=60, y=60, width=900, height=500)
    charts.add_chart("pie", [[3, 5, 2]], ["Share"], ["a", "b", "c"], x=1000, y=60, width=800, height=600)

    photo = deck.add_slide("Blank")
    photo.add_image(picture.read_bytes(), position=(200, 100), size=(640, None), description="A red square", name="red.png")

    skipped = deck.add_slide("Title Only", title="Skipped")
    skipped.skipped = True
    return deck


def view(deck: Presentation) -> list:
    """What a deck holds, without identifiers that differ from one build to the next."""
    out = []
    for slide in deck:
        ids = [d.identifier for d in slide.drawables]
        d = slide.to_dict()
        assert d.pop("movies") == []  # keynotejs has no video or sound yet
        d["builds"] = [
            {
                "target": f"drawable {ids.index(b.target)}" if isinstance(b.target, int) else b.target,
                "kind": b.kind,
                "effect": b.effect,
                "delivery": b.delivery,
                "duration": b.duration,
                "steps": b.steps,
            }
            for b in slide.builds
        ]
        out.append(d)
    return out


def rounded(value):
    """Positions and sizes are floats; compare them to a thousandth of a point."""
    if isinstance(value, list):
        return [rounded(v) for v in value]
    if isinstance(value, dict):
        return {k: rounded(v) for k, v in value.items()}
    if isinstance(value, float) or (isinstance(value, int) and not isinstance(value, bool)):
        r = round(value * 1000) / 1000
        return int(r) if r == int(r) else r
    return value


def fail(message: str, ours, theirs) -> None:
    print(message, file=sys.stderr)
    print("pykeynote: " + json.dumps(ours, indent=1, default=str), file=sys.stderr)
    print("keynotejs: " + json.dumps(theirs, indent=1, default=str), file=sys.stderr)
    sys.exit(1)


def main() -> None:
    folder = Path(sys.argv[1])
    if "--edited" in sys.argv[2:]:
        deck = Presentation.open(folder / "js-edited.key")
        assert deck[2].tables[0].cell(1, 1) == 43, deck[2].tables[0].rows
        chart = deck[3].charts[0]
        assert (chart.row_names, chart.column_names, chart.data) == (["Only"], ["P", "Q"], [[9, 8]]), chart.data
        assert deck[1].shapes[0].text == "Edited"
        return

    # keynotejs's deck, as keynotejs saw it, must be what pykeynote sees.
    theirs = json.loads((folder / "js.json").read_text())
    opened = Presentation.open(folder / "js.key")
    if rounded(view(opened)) != rounded(theirs["slides"]):
        fail("pykeynote reads keynotejs's deck differently", view(opened), theirs["slides"])
    if opened.to_markdown() != theirs["markdown"]:
        fail("pykeynote's Markdown of keynotejs's deck differs", opened.to_markdown(), theirs["markdown"])

    ours = scenario(folder / "red.png")
    ours.save(folder / "py.key")
    (folder / "py.json").write_text(json.dumps({"slides": view(ours), "markdown": ours.to_markdown()}, indent=1))


if __name__ == "__main__":
    main()
