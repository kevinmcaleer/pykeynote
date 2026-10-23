"""Deck operations for the command line and the MCP server.

Each function takes a path to a ``.key`` file, does one thing, and returns
plain JSON-ready data. Functions that change a deck save it straight away,
back to ``path`` or to ``output``, so every call stands on its own.
:data:`TOOLS` describes them with JSON Schemas for :mod:`pykeynote.mcp`.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional, Union

from .document import Presentation, Slide, themes
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


def add_build(
    path: str,
    index: int,
    target: str = "body",
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
        "name": "add_build",
        "function": add_build,
        "description": (
            "Add a build animation to a slide's title or body. Each build plays "
            "after the existing ones, one click per step. Saves the deck."
        ),
        "inputSchema": _schema(
            {
                "path": _PATH,
                "index": _INDEX,
                "target": {"type": "string", "enum": ["title", "body"], "default": "body"},
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
]

TOOLS_BY_NAME: Dict[str, Dict[str, Any]] = {t["name"]: t for t in TOOLS}


def call(name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        raise KeyError(f"unknown tool {name!r}")
    function: Callable[..., Any] = tool["function"]
    return function(**(arguments or {}))
