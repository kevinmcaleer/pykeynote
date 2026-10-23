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
pykeynote themes
```

Slide indexes start at 0, and negative ones count from the end. Each
`--body` is one paragraph; two leading spaces indent it one level. Editing
commands save the deck in place unless you pass `-o other.key`. pykeynote
only writes `.key` files.

## Using it from Claude (MCP)

`pykeynote mcp` runs a [Model Context Protocol](https://modelcontextprotocol.io)
server over stdio, so Claude and other MCP clients can read and edit decks.
It has no extra dependencies, and needs a pykeynote release newer than 0.2.0.
Its tools are `list_themes`, `deck_info`,
`read_slide`, `export_markdown`, `create_deck`, `edit_slide`, `add_slide`,
`delete_slide`, `move_slide`, `duplicate_slide`, `add_build` and
`clear_builds`. Editing tools save the deck when they finish, or write a copy
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
5. A command line tool and an MCP server for LLMs. **Done.** Next: more bundled themes, images, and builds on other shapes.

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
