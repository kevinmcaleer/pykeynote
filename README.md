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

???
Keep this one short.
```

## Roadmap

1. Read decks and export Markdown. **Done.**
2. Edit text and notes, then save. **Done.**
3. Add, duplicate, delete and reorder slides, set transitions and skipping, and build decks from Markdown. **Done.**
4. Build animations on titles and bodies. **Done.**
5. More bundled themes and switching a deck's theme. **Done.** Next: images, and builds on other shapes.

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
