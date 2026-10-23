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

## Images

```python
deck = Presentation.new()
slide = deck.add_slide("Title & Photo", title="Meet the robot")
slide.add_image("robot.jpg", description="A small wheeled robot")  # fills the photo placeholder

slide = deck.add_slide("Blank")
slide.add_image("logo.png", position=(1600, 40), size=(200, None))  # top right, 200 pt wide

for image in slide.images:      # back to front
    print(image.position, image.size, image.pixel_size, image.description, image.filename)
    open(image.name, "wb").write(image.data)

slide.replace_image(0, "new-logo.png")   # by index, Image, or placeholder tag such as "Media"
slide.remove_image(0)
```

`add_image` takes a path or bytes, as PNG, JPEG or GIF. With no position or
size it fills the slide's first media placeholder, cropping the picture to it
as Keynote does; otherwise the image goes on top, centred if no position is
given. A placeholder still showing the theme's sample photo has
`is_sample == True` and no `data`, because Keynote keeps those photos outside
the file. `slide.placeholders` lists the layout's placeholders in reading
order. Images can have builds too: `slide.add_build(image.identifier, "dissolve")`.

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

`pykeynote.themes()` lists the bundled themes, each at 16:9 and 4:3. They are
Basic White, Basic Black, Basic Color, Classic White, Color Gradient,
Minimalist Light, Minimalist Dark and Briefing (Keynote spells two of them
"Colour"; use the US spelling here). Start a
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

Images use Markdown's own syntax. One without a title fills the layout's
next photo placeholder; a title of `"x,y widthxheight"` puts it at that spot
instead. A slide with images and no `layout` comment gets a photo layout,
and `from_markdown` removes any placeholder left without a picture.
`to_markdown(image_dir="talk-images")` saves the pictures and links them
from there; image paths in `from_markdown` are relative to `base_dir`.

```markdown
# Meet the robot

![A small wheeled robot](talk-images/robot.jpg)
![Logo](talk-images/logo.png "1600,40 200x100")
```

## Command line

Installing pykeynote adds a `pykeynote` command. Add `--json` to any
command to get machine-readable output for scripts and LLM agents.

```sh
pykeynote new talk.key -m talk.md          # Markdown to .key (-m - reads stdin)
pykeynote info talk.key                    # theme, size, layouts, slide list
pykeynote show talk.key 1                  # one slide: text, notes, transition, builds
pykeynote export talk.key -o talk.md       # .key to Markdown
pykeynote edit talk.key 1 --title "Why robots?" --body "They're fun" --body "  Mostly" --notes "Short"
pykeynote edit talk.key 1 --transition dissolve --duration 1.5 --skip no
pykeynote add talk.key --layout "Title & Bullets" --title "One more" --at 2
pykeynote duplicate talk.key 1
pykeynote move talk.key 3 0
pykeynote delete talk.key -1
pykeynote build talk.key 1 --target body --effect dissolve
pykeynote theme talk.key "Basic Black" --layout Quote=Statement
pykeynote themes
pykeynote image talk.key 2 robot.png --alt "A robot arm"   # fills the media placeholder if there is one
pykeynote image talk.key 2 arm.png --x 100 --y 200 --width 600
pykeynote image talk.key 2 new.png --replace Media      # or an image id from 'show'
pykeynote shape talk.key 1 --kind star --text "New!" --fill "#ff3366" --x 1500 --y 100 --width 300 --height 300
pykeynote textbox talk.key 1 "Source: our survey" --x 100 --y 980
pykeynote table talk.key 3 --csv scores.csv             # or --row Name,Score --row Ada,3
pykeynote chart talk.key 4 column --csv sales.csv       # column names in row 1, row names in column 1
pykeynote build talk.key 4 --target 2655081             # build an object in, by its id from 'show'
pykeynote remove talk.key 4 2655081                     # delete a shape, table, chart or image
```

Slide indexes start at 0, and negative ones count from the end. `show`
lists each shape, table, chart and image with an id, which `build --target`
and `remove` take. Positions and sizes are in points from the slide's top
left; anything placed without `--x` and `--y` is centred. Each
`--body` is one paragraph; two leading spaces indent it one level. Editing
commands save the deck in place unless you pass `-o other.key`. pykeynote
only writes `.key` files.

## Using it from Claude (MCP)

`pykeynote mcp` runs a [Model Context Protocol](https://modelcontextprotocol.io)
server over stdio, so Claude and other MCP clients can read and edit decks.
It has no extra dependencies, and needs a pykeynote release newer than 0.2.0.
Its tools are `list_themes`, `deck_info`,
`read_slide`, `export_markdown`, `create_deck`, `edit_slide`, `add_slide`,
`delete_slide`, `move_slide`, `duplicate_slide`, `apply_theme`, `add_build`,
`clear_builds`, `add_image`, `replace_image`, `remove_image`, `add_shape`,
`add_text_box`, `add_table`, `add_chart` and `delete_drawable`. Editing tools save the deck when they finish, or write a copy
when given `output`.

For Claude Code:

```sh
claude mcp add keynote -- uvx --from pykeynote pykeynote mcp
# or, with pykeynote installed already:
claude mcp add keynote -- pykeynote mcp
```

For Claude Desktop, add this to `claude_desktop_config.json`
(Settings > Developer > Edit Config) and restart it:

```json
{
  "mcpServers": {
    "keynote": {
      "command": "uvx",
      "args": ["--from", "pykeynote", "pykeynote", "mcp"]
    }
  }
}
```

If you installed with pip instead of using `uvx`, set `"command"` to the full
path that `which pykeynote` prints and `"args"` to `["mcp"]`. Give Claude
absolute paths to decks, since the server's working directory isn't yours.
Then ask something like "Make a five-slide deck about robot arms in
~/Desktop/arms.key" or "Tighten the bullets on slide 3 of ~/Desktop/talk.key".

## Roadmap

1. Read decks and export Markdown. **Done.**
2. Edit text and notes, then save. **Done.**
3. Add, duplicate, delete and reorder slides, set transitions and skipping, and build decks from Markdown. **Done.**
4. Build animations on titles and bodies. **Done.**
5. More bundled themes and switching a deck's theme. **Done.**
6. A command line tool and an MCP server for LLMs. **Done.**
7. Images: read, add, fill placeholders, replace and remove, with Markdown support. **Done.** Images, shapes, tables and charts are in the CLI and MCP tools too. Next: video and audio (#33).
8. Shapes, text boxes, tables and charts, with builds on them and tables in Markdown. **Done.**

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
