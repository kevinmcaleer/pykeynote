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

## Roadmap

1. Read decks and export Markdown. **Done.**
2. Edit text and notes, then save. **Done.**
3. Add, duplicate, delete and reorder slides, set transitions and skipping, and build decks from Markdown. **Done.**
4. Build animations on titles and bodies. **Done.**
5. Images: read, add, fill placeholders, replace and remove, with Markdown support. **Done.** Next: more bundled themes, video and audio.

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
