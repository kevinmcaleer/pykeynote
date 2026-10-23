# pykeynote

Read, and soon write, Apple Keynote presentations from Python. pykeynote
works on `.key` files directly, so it runs anywhere Python does. You don't
need Keynote or a Mac.

A `.key` file is a zip of Snappy-compressed protobuf archives (`Index/*.iwa`)
plus images and media in `Data/`. Decoding comes from
[keynote-parser](https://github.com/psobot/keynote-parser), which supports
files saved by Keynote up to 14.5.

For JavaScript and TypeScript, the same library is in [`js/`](js/) as the
npm package [`@kevsmac/keynotejs`](https://www.npmjs.com/package/@kevsmac/keynotejs).

## Install

```sh
pip install pykeynote
```

For development, clone the repo and run `pip install -e ".[dev]"`.

## Reading a deck

```python
from pykeynote import Presentation

deck = Presentation.open("talk.key")
print(deck.theme, deck.size, deck.layouts)

for slide in deck:
    print(slide.index, slide.layout, slide.title)
    for para in slide.paragraphs:          # text, indent level, bulleted?
        print("  " * para.level, para.text)
    print(slide.notes, slide.transition.effect, slide.skipped)

print(deck.to_markdown())
```

`title` and `body` are `None` when the slide's layout hides that placeholder.

## Making and changing decks

```python
from pykeynote import Presentation, Paragraph, from_markdown

deck = Presentation.new()                 # Basic White, 16:9, no slides yet
# Presentation.new(aspect="4:3") gives Keynote's Standard 1024 x 768 size
deck.add_slide("Title", title="Robots!", body="Kevin McAleer")
slide = deck.add_slide(
    "Title & Bullets",
    title="Why robots?",
    body=[Paragraph("They're fun"), Paragraph("Mostly", level=1), "They're useful"],
    notes="Keep this one short.",
)
slide.set_transition("dissolve", 1.5)
deck.save("talk.key")

deck = Presentation.open("talk.key")
deck[1].title = "Why robots? 🤖"
deck.duplicate_slide(1)
deck.move_slide(2, 0)
deck.delete_slide(-1)
deck[0].skipped = True
deck.save()                               # back to talk.key

slide = deck[1]
slide.add_build("title", "move in")       # one click
slide.add_build("body", "dissolve")       # then one click per bullet
print(slide.builds)

deck = from_markdown(open("talk.md").read())
deck.save("from-markdown.key")
```

`add_slide` copies a slide that already uses the layout, so it keeps the
theme's look. A deck from `Presentation.new()` has one of every layout to
copy from, kept out of sight and left out when you save. For a deck you
opened, at least one slide must already use the layout.

## Shapes, tables and charts

```python
from pykeynote import Presentation

deck = Presentation.new()
slide = deck.add_slide("Title Only", title="Results")

# Shapes and text boxes. Positions and sizes are in points from the top left.
box = slide.add_shape("rounded rectangle", x=100, y=300, width=500, height=300,
                      text="Hello", fill="#3366ff")
slide.add_shape("star", style=3)          # one of the theme's six shape styles
slide.add_text_box("A note", x=100, y=700, width=800, height=60)
slide.add_build(box)                      # shapes can have builds too

# Tables: lists of text, numbers, True/False, or None for an empty cell.
table = slide.add_table(
    [["Name", "Score"], ["Ada", 42], ["Bob", 3.5]],
    x=700, y=300, header_rows=1, style=1,
)
table.set_cell(2, 1, 7)
print(table.rows, table.header_rows, table.column_widths)

# Charts: one list of values per row name.
slide = deck.add_slide("Blank")
chart = slide.add_chart("column", [[1, 2, 3], [4, 5, 6]],
                        row_names=["2024", "2025"], column_names=["Q1", "Q2", "Q3"])
slide.add_chart("pie", [[3, 5, 2]], ["Share"], ["A", "B", "C"], x=1100, y=200)
chart.set_data([[9, 8, 7]], ["2026"], ["Q1", "Q2", "Q3"])
chart.chart_type = "line"

for drawable in slide.drawables:          # shapes, text boxes, tables and charts
    print(drawable.to_dict())
deck.save("results.key")
```

Shape kinds are rectangle, rounded rectangle, oval, triangle, diamond,
pentagon, hexagon, octagon, star, arrow, double arrow and plus. Chart types
are column, bar, line, area, their stacked forms, pie, donut and scatter.
Each row of chart data is a series unless `series_by="column"`, which is the
default for pies and donuts because Keynote draws a pie from the first value
of each series (so a pie shows only its first row). The chart's box includes
room for its legend, shown when there is more than one series, and its axis
labels; `chart.position` and `chart.size` are the plot inside it.

New tables and charts are copied from a small deck Keynote made, bundled
with pykeynote, and take the look of your deck's theme. `slide.shapes`,
`slide.tables` and `slide.charts` read what is already on a slide, Keynote's
own included; `slide.delete_drawable(d)` removes one, and duplicated slides
get their own copies.

## Themes

`pykeynote.themes()` lists the bundled themes, each at 16:9 and 4:3. Start a
deck in one, or switch an existing deck to another:

```python
from pykeynote import Presentation, themes

print(themes())                           # ['Basic Black', 'Basic White', ...]
deck = Presentation.new("Basic Black", aspect="4:3")

deck = Presentation.open("talk.key")
deck.apply_theme("Basic Black")           # or: deck.theme = "Basic Black"
deck.apply_theme("Basic Black", layouts={"Quote": "Statement"})
deck.save("talk-dark.key")
```

`apply_theme` rebuilds each slide on the new theme's layout of the same
name, or the closest one that shows a title and body where the slide has
them (`deck.match_layout(name, title=True, body=True)` shows the choice).
Titles and bodies with their indent levels, notes, transitions, skipping
and builds on titles and bodies come along. Images, shapes, text boxes and
text formatting beyond the layout's own don't. The slide size stays 16:9 or
4:3 unless you pass `aspect=`.

The templates are made by Keynote 14.5 with `scripts/make_templates.py`.

## Markdown

`to_markdown()` writes one block per slide, separated by `---`. Slide
settings go in HTML comments, and presenter notes follow a `???` line:

```markdown
<!-- layout: Title & Bullets -->
<!-- transition: dissolve 1.5s -->
<!-- build: body, dissolve, by bullet, 1s -->
# Why robots?

- They're fun
  - Mostly
- They're useful

| Robot | Legs |
| --- | --- |
| Dog | 4 |

???
Keep this one short.
```

Tables are pipe tables both ways; the rows above the `| --- |` line are
header rows. A slide with a title and a table but no bullets gets the
"Title Only" layout.

## Roadmap

1. Read decks and export Markdown. **Done.**
2. Edit text and notes, then save. **Done.**
3. Add, duplicate, delete and reorder slides, set transitions and skipping, and build decks from Markdown. **Done.**
4. Build animations on titles and bodies. **Done.**
5. More bundled themes and switching a deck's theme. **Done.**
6. Shapes, text boxes, tables and charts, with builds on them and tables in Markdown. **Done.** Next: images.

## Driving Keynote directly (legacy)

`pykeynote.scripting` controls a running copy of Keynote on a Mac through
AppleScript and JXA. It can already edit decks, but it will be removed once
the file-based engine catches up.

## Tests

```sh
pytest                                    # everything that runs without Keynote
PYKEYNOTE_INTEGRATION=1 pytest            # also drive real Keynote (macOS)
```

The sample decks in `tests/fixtures/` were made in Keynote 14.5.
