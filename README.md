# pykeynote

Create, read and edit Apple Keynote presentations from Python. Files are
saved as native `.key` documents.

pykeynote drives Keynote itself through its scripting interface, so it needs
macOS with Keynote installed. The first time it runs, macOS asks whether your
terminal (or Python) may control Keynote. Say yes.

Without a `theme`, `Presentation.new` uses whatever default theme is set in
Keynote's settings.

## Install

```sh
pip install -e ".[dev]"
```

## Quick start

```python
from pykeynote import Presentation, list_themes

print(list_themes())                      # themes installed in Keynote

with Presentation.new(theme="Basic White", path="talk.key") as deck:
    print(deck.layouts)                   # master slides in the theme

    deck[0].update(title="Robots!", body="Kevin McAleer")
    slide = deck.add_slide(
        "Title & Bullets",
        title="Why robots?",
        body="They're fun\nThey're useful\nThey're everywhere",
        notes="Keep this one short.",
    )
    slide.set_transition("dissolve", duration=1.0)
    deck.save()
```

Open an existing deck and read it:

```python
deck = Presentation.open("talk.key")
for row in deck.read_slides():            # one call for the whole deck
    print(row["index"], row["layout"], row["title"])
deck.theme = "Basic Black"
deck.slides[2].move_to(0)
deck.slides[-1].delete()
deck.save("talk-v2.key")
deck.close()
```

### Slides

`Presentation.slides` returns `Slide` objects that point at positions. After
adding, deleting or moving slides, fetch them again.

| Attribute | Notes |
| --- | --- |
| `title`, `body`, `notes` | Read and write. The body has one line per bullet. |
| `layout` | Name of the master slide. Assign a name to change it. |
| `skipped` | Read and write. |
| `transition` / `set_transition(effect, duration, delay, automatic)` | Effects are listed in `pykeynote.EFFECTS`. |
| `read()` / `update(**fields)` | Read or write several fields in one call. |
| `move_to(index)`, `delete()` | |

## Tests

```sh
pytest                                    # unit tests, run anywhere
PYKEYNOTE_INTEGRATION=1 pytest            # also drive real Keynote (macOS)
```

The integration tests open and close their own scratch presentations.

## Not yet supported

Build animations on individual slide elements can't be set through Keynote's
scripting interface. Work on that is planned separately.
