"""Deck operations for the command line and the MCP server.

Each function takes a path to a ``.key`` file, does one thing, and returns
plain JSON-ready data. Functions that change a deck save it straight away,
back to ``path`` or to ``output``, so every call stands on its own.
:data:`TOOLS` describes them with JSON Schemas for :mod:`pykeynote.mcp`.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional, Union

from .charts import CHART_TYPES
from .document import Presentation, Slide, themes
from .drawables import SHAPE_KINDS
from .markdown import from_markdown
from .text import Paragraph

BodyInput = Union[str, List[Union[str, Dict[str, Any]]]]


def _full(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _check_key(path: str) -> str:
    path = _full(path)
    if not path.lower().endswith(".key"):
        raise ValueError(f"pykeynote writes Keynote .key files only, so the path must end in .key: {path!r}")
    return path


def _open(path: str) -> Presentation:
    path = _full(path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"no such deck: {path}")
    return Presentation.open(path)


def _save(deck: Presentation, output: Optional[str]) -> str:
    deck.save(_check_key(output) if output else deck.path)
    return deck.path


def _paragraphs(body: BodyInput) -> List[Union[str, Paragraph]]:
    if isinstance(body, str):
        return body.split("\n")
    out: List[Union[str, Paragraph]] = []
    for item in body:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict) and "text" in item:
            out.append(Paragraph(str(item["text"]), level=int(item.get("level", 0))))
        else:
            raise ValueError(f"each body item must be a string or {{'text': ..., 'level': ...}}, not {item!r}")
    return out


def slide_summary(slide: Slide) -> Dict[str, Any]:
    return {"index": slide.index, "layout": slide.layout, "title": slide.title, "skipped": slide.skipped}


def slide_detail(slide: Slide) -> Dict[str, Any]:
    out = slide.to_dict()
    # ids let add_build and delete_drawable point at a particular drawable or image
    for d, entry in zip(slide.drawables, out["drawables"]):
        entry["id"] = d.identifier
    for i, entry in zip(slide.images, out["images"]):
        entry["id"] = i.identifier
    out["paragraphs"] = [{"text": p.text, "level": p.level, "bulleted": p.bulleted} for p in slide.paragraphs]
    out["builds"] = [
        {"target": b.target, "kind": b.kind, "effect": b.effect, "delivery": b.delivery,
         "duration": b.duration, "steps": b.steps}
        for b in slide.builds
    ]
    return out


# --- reading ---------------------------------------------------------------------


def list_themes() -> Dict[str, Any]:
    return {"themes": themes(), "aspects": ["16:9", "4:3"]}


def deck_info(path: str) -> Dict[str, Any]:
    deck = _open(path)
    width, height = deck.size
    return {
        "path": deck.path,
        "theme": deck.theme,
        "size": {"width": width, "height": height},
        "layouts": deck.layouts,
        "slide_count": len(deck),
        "slides": [slide_summary(s) for s in deck],
    }


def read_slide(path: str, index: int) -> Dict[str, Any]:
    deck = _open(path)
    return slide_detail(deck[deck._check_index(index)])


def export_markdown(path: str, output: Optional[str] = None) -> Dict[str, Any]:
    markdown = _open(path).to_markdown()
    if output:
        output = _full(output)
        with open(output, "w", encoding="utf-8") as f:
            f.write(markdown)
    return {"markdown": markdown, "output": output}


# --- making and changing decks -----------------------------------------------------


def create_deck(
    path: str,
    markdown: Optional[str] = None,
    theme: str = "Basic White",
    aspect: str = "16:9",
    overwrite: bool = False,
) -> Dict[str, Any]:
    path = _check_key(path)
    if os.path.exists(path) and not overwrite:
        raise FileExistsError(f"{path} already exists; pass overwrite (--force on the command line) to replace it")
    if markdown and markdown.strip():
        deck = from_markdown(markdown, theme=theme, aspect=aspect)
    else:
        deck = Presentation.new(theme, aspect)
        deck.add_slide("Title", title="Title")
    deck.save(path)
    return deck_info(path)


def edit_slide(
    path: str,
    index: int,
    title: Optional[str] = None,
    body: Optional[BodyInput] = None,
    notes: Optional[str] = None,
    skipped: Optional[bool] = None,
    transition: Optional[str] = None,
    transition_duration: Optional[float] = None,
    output: Optional[str] = None,
) -> Dict[str, Any]:
    deck = _open(path)
    slide = deck[deck._check_index(index)]
    if title is not None:
        slide.title = title
    if body is not None:
        slide.body = _paragraphs(body)
    if notes is not None:
        slide.notes = notes
    if skipped is not None:
        slide.skipped = skipped
    if transition is not None:
        slide.set_transition(None if transition.lower() == "none" else transition, transition_duration)
    _save(deck, output)
    return slide_detail(slide)


def add_slide(
    path: str,
    layout: str = "Title & Bullets",
    title: Optional[str] = None,
    body: Optional[BodyInput] = None,
    notes: Optional[str] = None,
    index: Optional[int] = None,
    output: Optional[str] = None,
) -> Dict[str, Any]:
    deck = _open(path)
    slide = deck.add_slide(layout, title=title, body=None if body is None else _paragraphs(body),
                           notes=notes, index=index)
    _save(deck, output)
    return slide_detail(slide)


def delete_slide(path: str, index: int, output: Optional[str] = None) -> Dict[str, Any]:
    deck = _open(path)
    deck.delete_slide(index)
    _save(deck, output)
    return {"slide_count": len(deck), "slides": [slide_summary(s) for s in deck]}


def move_slide(path: str, index: int, to: int, output: Optional[str] = None) -> Dict[str, Any]:
    deck = _open(path)
    deck.move_slide(index, to)
    _save(deck, output)
    return {"slides": [slide_summary(s) for s in deck]}


def duplicate_slide(path: str, index: int, to: Optional[int] = None, output: Optional[str] = None) -> Dict[str, Any]:
    deck = _open(path)
    slide = deck.duplicate_slide(index, to)
    _save(deck, output)
    return slide_detail(slide)


def apply_theme(
    path: str,
    theme: str,
    aspect: Optional[str] = None,
    layouts: Optional[Dict[str, str]] = None,
    output: Optional[str] = None,
) -> Dict[str, Any]:
    deck = _open(path)
    deck.apply_theme(theme, aspect, layouts)
    return deck_info(_save(deck, output))


def add_build(
    path: str,
    index: int,
    target: Union[str, int] = "body",
    effect: str = "dissolve",
    delivery: Optional[str] = None,
    duration: float = 1.0,
    kind: str = "in",
    output: Optional[str] = None,
) -> Dict[str, Any]:
    deck = _open(path)
    slide = deck[deck._check_index(index)]
    slide.add_build(target, effect, delivery, duration, kind)
    _save(deck, output)
    return slide_detail(slide)


def clear_builds(path: str, index: int, output: Optional[str] = None) -> Dict[str, Any]:
    deck = _open(path)
    slide = deck[deck._check_index(index)]
    slide.clear_builds()
    _save(deck, output)
    return slide_detail(slide)


# --- images, shapes, tables and charts ----------------------------------------------


def _frame(x: Optional[float], y: Optional[float]) -> None:
    if (x is None) != (y is None):
        raise ValueError("give both x and y, or neither to centre it")


def _drawable(slide: Slide, drawable: int) -> Any:
    found = [d for d in slide.drawables if d.identifier == drawable]
    if found:
        return found[0]
    raise ValueError(
        f"no shape, text box, table or chart with id {drawable} on slide {slide.index}; "
        "read_slide lists them with their ids"
    )


def _image(slide: Slide, image: Union[int, str]) -> Any:
    """An image by its id, or a placeholder tag such as "Media"."""
    if isinstance(image, str):
        return image
    found = [i for i in slide.images if i.identifier == image]
    if found:
        return found[0]
    raise ValueError(f"no image with id {image} on slide {slide.index}; read_slide lists them with their ids")


def add_image(
    path: str,
    index: int,
    image: str,
    x: Optional[float] = None,
    y: Optional[float] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
    description: Optional[str] = None,
    placeholder: Union[None, bool, str] = None,
    output: Optional[str] = None,
) -> Dict[str, Any]:
    _frame(x, y)
    deck = _open(path)
    slide = deck[deck._check_index(index)]
    position = None if x is None else (x, y)
    size = None if width is None and height is None else (width, height)
    slide.add_image(_full(image), position, size, description, placeholder)
    _save(deck, output)
    return slide_detail(slide)


def replace_image(
    path: str,
    index: int,
    target: Union[int, str],
    image: str,
    description: Optional[str] = None,
    output: Optional[str] = None,
) -> Dict[str, Any]:
    deck = _open(path)
    slide = deck[deck._check_index(index)]
    slide.replace_image(_image(slide, target), _full(image), description)
    _save(deck, output)
    return slide_detail(slide)


def remove_image(path: str, index: int, target: Union[int, str], output: Optional[str] = None) -> Dict[str, Any]:
    deck = _open(path)
    slide = deck[deck._check_index(index)]
    slide.remove_image(_image(slide, target))
    _save(deck, output)
    return slide_detail(slide)


def add_shape(
    path: str,
    index: int,
    kind: str = "rectangle",
    text: Optional[BodyInput] = None,
    fill: Optional[str] = None,
    style: int = 0,
    x: Optional[float] = None,
    y: Optional[float] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
    output: Optional[str] = None,
) -> Dict[str, Any]:
    _frame(x, y)
    deck = _open(path)
    slide = deck[deck._check_index(index)]
    slide.add_shape(kind, x, y, width, height, None if text is None else _paragraphs(text), fill, style)
    _save(deck, output)
    return slide_detail(slide)


def add_text_box(
    path: str,
    index: int,
    text: BodyInput,
    x: Optional[float] = None,
    y: Optional[float] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
    output: Optional[str] = None,
) -> Dict[str, Any]:
    _frame(x, y)
    deck = _open(path)
    slide = deck[deck._check_index(index)]
    slide.add_text_box(_paragraphs(text), x, y, width, height)
    _save(deck, output)
    return slide_detail(slide)


def add_table(
    path: str,
    index: int,
    rows: List[List[Any]],
    header_rows: int = 1,
    header_columns: int = 0,
    style: int = 0,
    name: Optional[str] = None,
    x: Optional[float] = None,
    y: Optional[float] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
    output: Optional[str] = None,
) -> Dict[str, Any]:
    _frame(x, y)
    deck = _open(path)
    slide = deck[deck._check_index(index)]
    slide.add_table(rows, x, y, width, height, header_rows, header_columns, style, name)
    _save(deck, output)
    return slide_detail(slide)


def add_chart(
    path: str,
    index: int,
    chart_type: str,
    rows: List[List[Optional[float]]],
    row_names: List[str],
    column_names: List[str],
    series_by: Optional[str] = None,
    legend: Optional[bool] = None,
    style: int = 0,
    x: Optional[float] = None,
    y: Optional[float] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
    output: Optional[str] = None,
) -> Dict[str, Any]:
    _frame(x, y)
    deck = _open(path)
    slide = deck[deck._check_index(index)]
    slide.add_chart(chart_type, rows, row_names, column_names, x, y, width, height, style, series_by, legend)
    _save(deck, output)
    return slide_detail(slide)


def delete_drawable(path: str, index: int, drawable: int, output: Optional[str] = None) -> Dict[str, Any]:
    deck = _open(path)
    slide = deck[deck._check_index(index)]
    slide.delete_drawable(_drawable(slide, drawable))
    _save(deck, output)
    return slide_detail(slide)


# --- tool descriptions for the MCP server -------------------------------------------

_PATH = {"type": "string", "description": "Absolute path to a Keynote .key file (~ is allowed)"}
_INDEX = {"type": "integer", "description": "Slide index, from 0; negative counts from the end"}
_OUTPUT = {"type": "string", "description": "Save to this .key path instead of changing the file in place"}
_BODY = {
    "description": (
        "Body text: a string with one paragraph per line, or a list of strings "
        "or {text, level} objects, where level is the bullet indent from 0"
    ),
    "anyOf": [
        {"type": "string"},
        {"type": "array", "items": {"anyOf": [
            {"type": "string"},
            {"type": "object", "properties": {"text": {"type": "string"}, "level": {"type": "integer", "minimum": 0}},
             "required": ["text"]},
        ]}},
    ],
}
_UNITS = "Positions and sizes are in points from the slide's top left; deck_info gives the slide size."
_FRAME = {
    "x": {"type": "number", "description": "Left edge, in points"},
    "y": {"type": "number", "description": "Top edge, in points"},
    "width": {"type": "number"},
    "height": {"type": "number"},
}
_STYLE = {"type": "integer", "minimum": 0, "maximum": 5, "default": 0, "description": "One of the theme's six styles"}
_IMAGE_TARGET = {
    "description": "The image's id from read_slide, or a media placeholder tag such as Media",
    "anyOf": [{"type": "integer"}, {"type": "string"}],
}
_MARKDOWN_FORMAT = (
    "Slides are separated by a line holding only ---. Each slide starts with a "
    "# heading for its title, then bullets (- item, indent two spaces per level) "
    "or plain paragraphs. Optional settings go in HTML comments before the "
    "heading: <!-- layout: Title & Bullets -->, <!-- transition: dissolve 1.5s -->, "
    "<!-- build: body, dissolve, by bullet, 1s -->, <!-- skipped: true -->. "
    "Presenter notes follow a line holding only ???."
)


def _schema(properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


TOOLS: List[Dict[str, Any]] = [
    {
        "name": "list_themes",
        "function": list_themes,
        "description": "List the themes and slide sizes pykeynote can make new decks in.",
        "inputSchema": _schema({}, []),
        "readOnly": True,
    },
    {
        "name": "deck_info",
        "function": deck_info,
        "description": (
            "Open a Keynote .key deck and describe it: theme, size, the layouts "
            "(master slides) it offers, and each slide's index, layout and title."
        ),
        "inputSchema": _schema({"path": _PATH}, ["path"]),
        "readOnly": True,
    },
    {
        "name": "read_slide",
        "function": read_slide,
        "description": (
            "Read one slide: layout, title, body paragraphs with indent levels, "
            "presenter notes, transition, builds and whether it is skipped. "
            "title or body is null when the slide's layout doesn't show it."
        ),
        "inputSchema": _schema({"path": _PATH, "index": _INDEX}, ["path", "index"]),
        "readOnly": True,
    },
    {
        "name": "export_markdown",
        "function": export_markdown,
        "description": "Convert a whole deck to Markdown. " + _MARKDOWN_FORMAT,
        "inputSchema": _schema(
            {"path": _PATH, "output": {"type": "string", "description": "Also write the Markdown to this file"}},
            ["path"],
        ),
        "readOnly": True,
    },
    {
        "name": "create_deck",
        "function": create_deck,
        "description": (
            "Create a new Keynote .key file, from Markdown if given, otherwise "
            "with a single title slide. Won't replace an existing file unless "
            "overwrite is true. " + _MARKDOWN_FORMAT
        ),
        "inputSchema": _schema(
            {
                "path": {"type": "string", "description": "Where to save the new .key file"},
                "markdown": {"type": "string", "description": "The deck as Markdown"},
                "theme": {"type": "string", "description": "A theme from list_themes", "default": "Basic White"},
                "aspect": {"type": "string", "enum": ["16:9", "4:3"], "default": "16:9"},
                "overwrite": {"type": "boolean", "default": False},
            },
            ["path"],
        ),
    },
    {
        "name": "edit_slide",
        "function": edit_slide,
        "description": (
            "Change a slide's title, body, presenter notes, skipped flag or "
            "transition, keeping the theme's formatting. Fields left out stay "
            "as they are. Saves the deck."
        ),
        "inputSchema": _schema(
            {
                "path": _PATH,
                "index": _INDEX,
                "title": {"type": "string"},
                "body": _BODY,
                "notes": {"type": "string"},
                "skipped": {"type": "boolean"},
                "transition": {"type": "string", "description": "e.g. dissolve, push, magic move, or none"},
                "transition_duration": {"type": "number", "description": "Seconds"},
                "output": _OUTPUT,
            },
            ["path", "index"],
        ),
    },
    {
        "name": "add_slide",
        "function": add_slide,
        "description": (
            "Add a slide using one of the deck's layouts (see deck_info), at the "
            "end unless index is given. For an existing deck, at least one slide "
            "must already use that layout. Saves the deck."
        ),
        "inputSchema": _schema(
            {
                "path": _PATH,
                "layout": {"type": "string", "default": "Title & Bullets"},
                "title": {"type": "string"},
                "body": _BODY,
                "notes": {"type": "string"},
                "index": {"type": "integer", "description": "Position for the new slide"},
                "output": _OUTPUT,
            },
            ["path"],
        ),
    },
    {
        "name": "delete_slide",
        "function": delete_slide,
        "description": "Delete a slide. Saves the deck.",
        "inputSchema": _schema({"path": _PATH, "index": _INDEX, "output": _OUTPUT}, ["path", "index"]),
        "destructive": True,
    },
    {
        "name": "move_slide",
        "function": move_slide,
        "description": "Move the slide at index so it ends up at position to. Saves the deck.",
        "inputSchema": _schema(
            {"path": _PATH, "index": _INDEX, "to": {"type": "integer"}, "output": _OUTPUT}, ["path", "index", "to"]
        ),
    },
    {
        "name": "duplicate_slide",
        "function": duplicate_slide,
        "description": "Copy a slide. The copy goes right after it unless to is given. Saves the deck.",
        "inputSchema": _schema(
            {"path": _PATH, "index": _INDEX, "to": {"type": "integer"}, "output": _OUTPUT}, ["path", "index"]
        ),
    },
    {
        "name": "apply_theme",
        "function": apply_theme,
        "description": (
            "Switch a deck to one of the bundled themes (see list_themes), keeping "
            "each slide's title, body, notes, transition, skipping and builds. "
            "Slides move to the new theme's layout of the same name, or the closest "
            "match. Images, shapes and extra text boxes are not carried over. Saves the deck."
        ),
        "inputSchema": _schema(
            {
                "path": _PATH,
                "theme": {"type": "string", "description": "A theme from list_themes"},
                "aspect": {"type": "string", "enum": ["16:9", "4:3"],
                           "description": "Defaults to the closer of the two to the current size"},
                "layouts": {"type": "object", "additionalProperties": {"type": "string"},
                            "description": "Old layout name to new layout name, e.g. {\"Quote\": \"Statement\"}"},
                "output": _OUTPUT,
            },
            ["path", "theme"],
        ),
    },
    {
        "name": "add_build",
        "function": add_build,
        "description": (
            "Add a build animation to a slide's title, body or another object on it. Each build plays "
            "after the existing ones, one click per step. Saves the deck."
        ),
        "inputSchema": _schema(
            {
                "path": _PATH,
                "index": _INDEX,
                "target": {
                    "description": "title, body, or the id of a shape, text box, table, chart or image (see read_slide)",
                    "anyOf": [{"type": "string", "enum": ["title", "body"]}, {"type": "integer"}],
                    "default": "body",
                },
                "effect": {"type": "string", "description": "e.g. dissolve, move in", "default": "dissolve"},
                "delivery": {"type": "string", "enum": ["all at once", "by bullet"]},
                "duration": {"type": "number", "default": 1.0},
                "kind": {"type": "string", "enum": ["in", "out"], "default": "in"},
                "output": _OUTPUT,
            },
            ["path", "index"],
        ),
    },
    {
        "name": "clear_builds",
        "function": clear_builds,
        "description": "Remove every build animation from a slide. Saves the deck.",
        "inputSchema": _schema({"path": _PATH, "index": _INDEX, "output": _OUTPUT}, ["path", "index"]),
        "destructive": True,
    },
    {
        "name": "add_image",
        "function": add_image,
        "description": (
            "Add a PNG, JPEG or GIF image file to a slide. With no x, y, width or "
            "height it fills the layout's first empty media placeholder, cropped to "
            "fit, if there is one; otherwise it goes on top, centred unless x and y "
            "are given. Give width or height alone to keep the picture's shape. "
            + _UNITS + " Saves the deck."
        ),
        "inputSchema": _schema(
            {
                "path": _PATH,
                "index": _INDEX,
                "image": {"type": "string", "description": "Path to the image file"},
                **_FRAME,
                "description": {"type": "string", "description": "Accessibility description (alt text)"},
                "placeholder": {
                    "description": "false to never use a placeholder, or a placeholder tag such as Media-2",
                    "anyOf": [{"type": "boolean"}, {"type": "string"}],
                },
                "output": _OUTPUT,
            },
            ["path", "index", "image"],
        ),
    },
    {
        "name": "replace_image",
        "function": replace_image,
        "description": (
            "Swap the picture in an existing image or media placeholder for a new "
            "image file, keeping its place and crop. Saves the deck."
        ),
        "inputSchema": _schema(
            {"path": _PATH, "index": _INDEX, "target": _IMAGE_TARGET,
             "image": {"type": "string", "description": "Path to the new image file"},
             "description": {"type": "string", "description": "Accessibility description (alt text)"},
             "output": _OUTPUT},
            ["path", "index", "target", "image"],
        ),
    },
    {
        "name": "remove_image",
        "function": remove_image,
        "description": "Delete an image from a slide, with any builds on it. Saves the deck.",
        "inputSchema": _schema(
            {"path": _PATH, "index": _INDEX, "target": _IMAGE_TARGET, "output": _OUTPUT}, ["path", "index", "target"]
        ),
        "destructive": True,
    },
    {
        "name": "add_shape",
        "function": add_shape,
        "description": (
            "Add a shape, optionally with text in it, in one of the theme's six "
            "shape styles. Centred unless x and y are given; 400 x 300 unless "
            "width and height are given. " + _UNITS + " Saves the deck."
        ),
        "inputSchema": _schema(
            {
                "path": _PATH,
                "index": _INDEX,
                "kind": {"type": "string", "enum": list(SHAPE_KINDS), "default": "rectangle"},
                "text": _BODY,
                "fill": {"type": "string", "description": "Fill colour, e.g. #3366ff or a CSS colour name"},
                "style": _STYLE,
                **_FRAME,
                "output": _OUTPUT,
            },
            ["path", "index"],
        ),
    },
    {
        "name": "add_text_box",
        "function": add_text_box,
        "description": (
            "Add a free text box in the theme's text style, for text outside the "
            "title and body. " + _UNITS + " Saves the deck."
        ),
        "inputSchema": _schema(
            {"path": _PATH, "index": _INDEX, "text": _BODY, **_FRAME, "output": _OUTPUT}, ["path", "index", "text"]
        ),
    },
    {
        "name": "add_table",
        "function": add_table,
        "description": (
            "Add a table. rows is a list of rows, each a list of cells: text, "
            "numbers, true/false, or null for empty. The first header_rows rows "
            "are headers. Centred unless x and y are given. " + _UNITS + " Saves the deck."
        ),
        "inputSchema": _schema(
            {
                "path": _PATH,
                "index": _INDEX,
                "rows": {"type": "array", "items": {"type": "array", "items": {
                    "anyOf": [{"type": "string"}, {"type": "number"}, {"type": "boolean"}, {"type": "null"}]}}},
                "header_rows": {"type": "integer", "minimum": 0, "default": 1},
                "header_columns": {"type": "integer", "minimum": 0, "default": 0},
                "style": _STYLE,
                "name": {"type": "string", "description": "The table's name"},
                **_FRAME,
                "output": _OUTPUT,
            },
            ["path", "index", "rows"],
        ),
    },
    {
        "name": "add_chart",
        "function": add_chart,
        "description": (
            "Add a chart. rows holds one list of values per row name, with one "
            "value per column name. Each row is a series, unless series_by is "
            "column (the default for pie and donut, whose slices are the first "
            "row's values). Centred unless x and y are given. " + _UNITS + " Saves the deck."
        ),
        "inputSchema": _schema(
            {
                "path": _PATH,
                "index": _INDEX,
                "chart_type": {"type": "string", "enum": list(CHART_TYPES)},
                "rows": {"type": "array", "items": {"type": "array", "items": {"type": ["number", "null"]}}},
                "row_names": {"type": "array", "items": {"type": "string"}},
                "column_names": {"type": "array", "items": {"type": "string"}},
                "series_by": {"type": "string", "enum": ["row", "column"]},
                "legend": {"type": "boolean", "description": "Default: shown when there is more than one series"},
                "style": _STYLE,
                **_FRAME,
                "output": _OUTPUT,
            },
            ["path", "index", "chart_type", "rows", "row_names", "column_names"],
        ),
    },
    {
        "name": "delete_drawable",
        "function": delete_drawable,
        "description": (
            "Delete a shape, text box, table or chart from a slide, by the id "
            "read_slide shows. Clear the slide's builds first if one targets it. Saves the deck."
        ),
        "inputSchema": _schema(
            {"path": _PATH, "index": _INDEX, "drawable": {"type": "integer", "description": "Its id from read_slide"},
             "output": _OUTPUT},
            ["path", "index", "drawable"],
        ),
        "destructive": True,
    },
]

TOOLS_BY_NAME: Dict[str, Dict[str, Any]] = {t["name"]: t for t in TOOLS}


def call(name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        raise KeyError(f"unknown tool {name!r}")
    function: Callable[..., Any] = tool["function"]
    return function(**(arguments or {}))
