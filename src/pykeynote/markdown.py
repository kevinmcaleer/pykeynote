"""Convert a presentation to Markdown.

Each slide becomes a block, and blocks are separated by ``---``::

    <!-- layout: Title & Bullets -->
    <!-- transition: wipe 0.75s from left -->
    <!-- build: title, wipe, all at once, 1s, from left -->
    <!-- build: subtitle, wipe, all at once, 1s, after previous, delay 0.1s -->
    <!-- build: body, fade and move, by bullet, 0.3s -->
    # Slide title
    ## A subtitle

    - A bullet
      - An indented bullet

    A paragraph without a bullet

    | Name | Score |
    | --- | --- |
    | Ada | 42 |
    ![A robot arm](images/arm.png)
    ![Logo](images/logo.png "1600,40 200x100")

    ???
    Presenter notes

Tables are pipe tables; a ``| --- |`` line ends the header rows. Slide
settings go in HTML comments, so the Markdown still renders cleanly
elsewhere. Notes follow a line holding only ``???``, as in remark.js.
A ``##`` heading straight after the ``#`` title is the slide's subtitle.

A build comment holds a target (title, subtitle or body), an effect, then
in any order: a delivery ("all at once" or "by bullet"), a duration
("1s"), "in" or "out", a start ("on click", "after previous" or "with
previous"), a delay ("delay 0.1s") and a direction ("from left", "from
right", "from top" or "from bottom").

An image fills the layout's next media placeholder, or, if its title gives
a frame (``"x,y"`` or ``"x,y widthxheight"``, in points), goes exactly there.
Videos and sounds (``.mp4``, ``.m4v``, ``.mov``, ``.m4a``) use the same
syntax; a sound has no picture, so it never fills a placeholder.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from .builds import STARTS, direction_value, direction_name
from .text import Paragraph

if TYPE_CHECKING:
    from .document import Presentation, Slide

SLIDE_SEPARATOR = "---"
NOTES_MARKER = "???"

# A plain paragraph starting like this would read as Markdown syntax.
_NEEDS_ESCAPE = re.compile(r"^(#|[-*+] |\d+[.)] |>|---|\?\?\?|<!--|!\[)")


def _fmt_seconds(value: float) -> str:
    return f"{value:g}s"


def _fmt_number(value: float) -> str:
    return f"{round(value, 1):g}"


MEDIA_EXTENSIONS = (".mp4", ".m4v", ".mov", ".m4a")
_AUDIO_EXTENSIONS = (".m4a",)


def _image_names(presentation: "Presentation") -> Dict[str, Set[str]]:
    """Each name images, videos and sounds were added under, with the files stored under it."""
    names: Dict[str, Set[str]] = {}
    for slide in presentation.slides:
        for item in [*slide.images, *slide.movies]:
            if item.name:
                names.setdefault(item.name, set()).add(item.filename)
    return names


def _reading_order(items: List[Any]) -> List[Any]:
    """Left to right and top to bottom, with tops within 20 points of each other as one row."""
    rows: List[List[Any]] = []
    for item in sorted(items, key=lambda i: i.position[1]):
        if rows and item.position[1] - rows[-1][0].position[1] <= 20:
            rows[-1].append(item)
        else:
            rows.append([item])
    return [item for row in rows for item in sorted(row, key=lambda i: i.position[0])]


def _image_lines(slide: "Slide", image_dir: Optional[str], names: Dict[str, Set[str]]) -> List[str]:
    lines = []
    images = [i for i in slide.images if not i.is_sample]
    movies = [m for m in slide.movies if m.data is not None]
    placed = _reading_order([i for i in images + movies if i.placeholder is not None])
    free = [i for i in images + movies if i.placeholder is None]
    for image in placed + free:
        # The name it was added under, unless another picture in the deck has it too.
        path = image.name if names.get(image.name, {image.filename}) == {image.filename} else image.filename
        if image_dir is not None:
            os.makedirs(image_dir, exist_ok=True)
            with open(os.path.join(image_dir, path), "wb") as fh:
                fh.write(image.data)
            path = image_dir.replace(os.sep, "/").rstrip("/") + "/" + path
        if " " in path or ")" in path:
            path = f"<{path}>"
        alt = " ".join(image.description.split()).replace("]", "\\]")
        frame = ""
        if getattr(image, "audio_only", False):
            # A sound has no size, and sits in the middle of the slide unless moved.
            (x, y), (w, h) = image.position, slide.presentation.size
            if (round(x, 1), round(y, 1)) != (round(w / 2, 1), round(h / 2, 1)):
                frame = f' "{_fmt_number(x)},{_fmt_number(y)}"'
        elif image.placeholder is None:
            (x, y), (w, h) = image.position, image.size
            frame = f' "{_fmt_number(x)},{_fmt_number(y)} {_fmt_number(w)}x{_fmt_number(h)}"'
        lines.append(f"![{alt}]({path}{frame})")
    return lines


def slide_to_markdown(slide: "Slide", image_dir: Optional[str] = None, _names: Optional[Dict[str, Set[str]]] = None) -> str:
    lines: List[str] = [f"<!-- layout: {slide.layout} -->"]
    t = slide.transition
    if t.effect:
        direction = f" {t.direction}" if t.direction else ""
        lines.append(f"<!-- transition: {t.effect} {_fmt_seconds(t.duration)}{direction} -->")
    if slide.skipped:
        lines.append("<!-- skipped -->")
    for b in slide.builds:
        if isinstance(b.target, str):
            parts = [b.target, b.effect, "by bullet" if b.delivery == "By Paragraph" else b.delivery.lower()]
            parts.append(_fmt_seconds(b.duration))
            if b.kind != "in":
                parts.append(b.kind)
            if b.start != "on click":
                parts.append(b.start)
            if b.delay:
                parts.append(f"delay {_fmt_seconds(b.delay)}")
            if b.direction:
                parts.append(b.direction)
            lines.append(f"<!-- build: {', '.join(parts)} -->")

    if slide.title is not None and slide.title.strip():
        lines.append("# " + " ".join(slide.title.split()))
        subtitle = slide.subtitle
        if subtitle is not None:
            lines.append("## " + " ".join(subtitle.split()))

    body: List[str] = []
    for para in slide.paragraphs:
        text = para.text.replace("\n", "<br>").strip()
        if not text:
            continue
        if para.bulleted:
            body.append("  " * para.level + "- " + text)
        else:
            if body:
                body.append("")
            body.append("\\" + text if _NEEDS_ESCAPE.match(text) else text)
    if body:
        lines.append("")
        lines.extend(body)

    for table in slide.tables:
        lines.append("")
        lines.extend(table_to_markdown(table.rows, table.header_rows))
    images = _image_lines(slide, image_dir, _image_names(slide.presentation) if _names is None else _names)
    if images:
        lines.append("")
        lines.extend(images)

    notes = slide.notes.strip()
    if notes:
        lines.extend(["", NOTES_MARKER, notes])
    return "\n".join(lines) + "\n"


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        return f"{value:g}" if abs(value) < 1e15 else repr(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def table_to_markdown(rows: List[List[Any]], header_rows: int = 1) -> List[str]:
    """A pipe table, one line per row. Header rows go above the ``---`` line; with none, it goes first."""
    out = []
    width = max(len(r) for r in rows)
    separator = "| " + " | ".join(["---"] * width) + " |"
    if header_rows == 0:
        out.append("| " + " | ".join([""] * width) + " |")
        out.append(separator)
    for i, row in enumerate(rows):
        out.append("| " + " | ".join(_cell_text(v) for v in row) + " |")
        if i + 1 == header_rows:
            out.append(separator)
    return out


def to_markdown(presentation: "Presentation", image_dir: Optional[str] = None) -> str:
    """The presentation as Markdown. With ``image_dir``, images are saved there and linked by that path."""
    names = _image_names(presentation)
    return f"\n{SLIDE_SEPARATOR}\n\n".join(slide_to_markdown(s, image_dir, names) for s in presentation.slides)


# --- Markdown to a presentation -------------------------------------------------

_COMMENT = re.compile(r"^<!--\s*(.*?)\s*-->$")
_HEADING = re.compile(r"^#{1,2}\s+(.*)$")
_BULLET = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(.*)$")
_TRANSITION = re.compile(r"^(.*?)(?:\s+([\d.]+)\s*s)?(?:\s+((?:from|left|right|top|bottom)\b.*))?$")
_IMAGE = re.compile(r'^!\[((?:\\.|[^\]])*)\]\(\s*(<[^>]*>|[^\s)]+)(?:\s+"([^"]*)")?\s*\)$')
_FRAME = re.compile(r"^\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)(?:\s+([\d.]+)\s*[x×]\s*([\d.]+))?\s*$")


@dataclass
class ImageSpec:
    """An image parsed from Markdown. ``position`` and ``size`` are set when its title gives a frame."""

    path: str
    description: str = ""
    position: Optional[Tuple[float, float]] = None
    size: Optional[Tuple[float, float]] = None


@dataclass
class SlideSpec:
    """One slide parsed from Markdown, before it is added to a deck."""

    layout: Optional[str] = None
    title: Optional[str] = None
    subtitle: Optional[str] = None
    paragraphs: List[Paragraph] = field(default_factory=list)
    notes: str = ""
    transition: Optional[str] = None
    transition_duration: Optional[float] = None
    transition_direction: Optional[str] = None
    skipped: bool = False
    builds: List[dict] = field(default_factory=list)
    tables: List["TableSpec"] = field(default_factory=list)
    images: List[ImageSpec] = field(default_factory=list)

    def default_layout(self) -> str:
        bulleted = any(p.bulleted for p in self.paragraphs)
        photos = len([i for i in self.images if i.position is None and not i.path.lower().endswith(_AUDIO_EXTENSIONS)])
        if photos:
            if self.paragraphs:
                return "Title, Bullets & Photo"
            if self.title:
                return "Title & Photo"
            return "Photo" if photos == 1 else "Photo - 3 Up"
        if self.tables and not self.paragraphs:
            return "Title Only" if self.title else "Blank"
        if self.title and self.paragraphs:
            return "Title & Bullets" if bulleted else "Title"
        if self.title:
            return "Title Only"
        if self.paragraphs:
            return "Bullets" if bulleted else "Statement"
        return "Blank"


@dataclass
class TableSpec:
    rows: List[List[Any]]
    header_rows: int = 0


_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEPARATOR = re.compile(r"^\s*\|(\s*:?-{3,}:?\s*\|)+\s*$")


def _split_row(line: str) -> List[str]:
    inner = line.strip()[1:-1]
    cells = re.split(r"(?<!\\)\|", inner)
    return [c.strip().replace("\\|", "|") for c in cells]


def _cell_value(text: str) -> Any:
    text = text.replace("<br>", "\n")
    if text == "":
        return None
    if text in ("TRUE", "FALSE"):
        return text == "TRUE"
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?", text):
        return float(text)
    return text


def parse_table(lines: List[str]) -> TableSpec:
    rows: List[List[Any]] = []
    header_rows = 0
    for line in lines:
        if _TABLE_SEPARATOR.match(line):
            header_rows = len(rows)
            continue
        rows.append([_cell_value(c) for c in _split_row(line)])
    if header_rows and all(v is None for v in rows[0]) and header_rows == 1:
        rows.pop(0)  # an empty header row stands for no header
        header_rows = 0
    width = max(len(r) for r in rows)
    return TableSpec([r + [None] * (width - len(r)) for r in rows], header_rows)


def _clean(text: str) -> str:
    text = text.strip().replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    return text[1:] if text.startswith("\\") else text


def _is_direction(text: str) -> bool:
    try:
        direction_value(text)
    except ValueError:
        return False
    return True


def _parse_build(value: str) -> dict:
    """Read ``target, effect[, delivery][, 1.5s][, in|out][, start][, delay 0.1s][, direction]`` from a build comment."""
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if len(parts) < 2:
        raise ValueError(f"a build needs at least a target and an effect: {value!r}")
    build: Dict[str, Any] = {"target": parts[0].lower(), "effect": parts[1]}
    for part in parts[2:]:
        low = " ".join(part.lower().replace("-", " ").split())
        delay = re.fullmatch(r"delay\s*([\d.]+)\s*s?", low)
        if re.fullmatch(r"[\d.]+\s*s", low):
            build["duration"] = float(low.rstrip("s").strip())
        elif delay:
            build["delay"] = float(delay.group(1))
        elif low in ("in", "out"):
            build["kind"] = low
        elif low in STARTS:
            build["start"] = low
        elif _is_direction(low):
            build["direction"] = direction_name(direction_value(low))
        else:
            build["delivery"] = low
    return build


def _parse_image(match: "re.Match[str]") -> ImageSpec:
    alt, path, title = match.group(1), match.group(2), match.group(3)
    if path.startswith("<") and path.endswith(">"):
        path = path[1:-1]
    image = ImageSpec(path, re.sub(r"\\(.)", r"\1", alt))
    frame = _FRAME.match(title or "")
    if frame:
        image.position = (float(frame.group(1)), float(frame.group(2)))
        if frame.group(3):
            image.size = (float(frame.group(3)), float(frame.group(4)))
    return image


def parse_markdown(text: str) -> List[SlideSpec]:
    """Split Markdown in the :func:`to_markdown` format into slide specs."""
    blocks: List[List[str]] = [[]]
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.strip() == SLIDE_SEPARATOR:
            blocks.append([])
        else:
            blocks[-1].append(line)

    specs = []
    for block in blocks:
        if not any(line.strip() for line in block):
            continue
        spec = SlideSpec()
        notes: Optional[List[str]] = None
        pending: List[str] = []  # lines of a plain paragraph being collected
        table_lines: List[str] = []

        def flush() -> None:
            if pending:
                spec.paragraphs.append(Paragraph(_clean(" ".join(s.strip() for s in pending)), 0, False))
                pending.clear()
            if table_lines:
                spec.tables.append(parse_table(table_lines))
                table_lines.clear()

        for line in block:
            stripped = line.strip()
            if notes is not None:
                notes.append(line)
                continue
            if stripped == NOTES_MARKER:
                flush()
                notes = []
                continue
            comment = _COMMENT.match(stripped)
            if comment:
                flush()
                key, _, value = comment.group(1).partition(":")
                key, value = key.strip().lower(), value.strip()
                if key == "layout":
                    spec.layout = value
                elif key == "transition":
                    m = _TRANSITION.match(value)
                    spec.transition = m.group(1).strip()
                    spec.transition_duration = float(m.group(2)) if m.group(2) else None
                    spec.transition_direction = m.group(3).strip() if m.group(3) else None
                elif key == "skipped":
                    spec.skipped = value.lower() not in ("false", "no", "0")
                elif key == "build":
                    spec.builds.append(_parse_build(value))
                continue
            image = _IMAGE.match(stripped)
            if image:
                flush()
                spec.images.append(_parse_image(image))
                continue
            heading = _HEADING.match(stripped)
            if heading and spec.title is None and not spec.paragraphs and not pending:
                spec.title = _clean(heading.group(1))
                continue
            if (
                heading
                and stripped.startswith("## ")
                and spec.title is not None
                and spec.subtitle is None
                and not spec.paragraphs
                and not pending
            ):
                spec.subtitle = _clean(heading.group(1))
                continue
            if _TABLE_ROW.match(line) and not pending:
                table_lines.append(line)
                continue
            if table_lines:
                flush()
            bullet = _BULLET.match(line)
            if bullet:
                flush()
                indent = len(bullet.group(1).expandtabs(4))
                spec.paragraphs.append(Paragraph(_clean(bullet.group(2)), indent // 2, True))
                continue
            if not stripped:
                flush()
                continue
            pending.append(line)
        flush()
        if notes is not None:
            spec.notes = "\n".join(notes).strip()
        specs.append(spec)
    return specs


def from_markdown(
    text: str, theme: str = "Basic White", aspect: str = "16:9", base_dir: Optional[str] = None
) -> "Presentation":
    """Build a new presentation from Markdown in the :func:`to_markdown` format.

    A slide without a ``layout`` comment gets one from its content: title and
    bullets give "Title & Bullets", a title alone "Title Only", an image with
    a title "Title & Photo", and so on. Image paths are relative to
    ``base_dir``, or the current directory. Media placeholders left without
    an image are removed, rather than showing the theme's sample photos.
    """
    from .document import Presentation

    deck = Presentation.new(theme, aspect)
    available = set(deck.layouts)
    for spec in parse_markdown(text):
        layout = spec.layout or spec.default_layout()
        if layout not in available:
            layout = deck.match_layout(layout, spec.title is not None, bool(spec.paragraphs))
        slide = deck.add_slide(layout)
        if spec.title is not None:
            if slide.title is None:
                raise ValueError(f"the {layout!r} layout doesn't show a title, for {spec.title!r}")
            slide.title = spec.title
        if spec.paragraphs:
            if slide.body is None:
                raise ValueError(f"the {layout!r} layout doesn't show a body, for {spec.paragraphs[0].text!r}")
            slide.body = spec.paragraphs
        if spec.subtitle is not None:
            slide.add_subtitle(spec.subtitle)
        if spec.notes:
            slide.notes = spec.notes
        if spec.transition:
            slide.set_transition(spec.transition, spec.transition_duration, direction=spec.transition_direction)
        if spec.skipped:
            slide.skipped = True
        _place_tables(slide, spec)
        for image in spec.images:
            path = image.path
            if not re.match(r"^[a-z]+://", path) and not os.path.isabs(path):
                path = os.path.join(base_dir or os.getcwd(), path)
            ext = os.path.splitext(image.path.lower())[1]
            if ext in _AUDIO_EXTENSIONS:
                slide.add_audio(path, image.position, image.description)
            elif ext in MEDIA_EXTENSIONS and image.position is not None:
                slide.add_movie(path, image.position, image.size, image.description, placeholder=False)
            elif ext in MEDIA_EXTENSIONS:
                slide.add_movie(path, description=image.description)
            elif image.position is not None:
                slide.add_image(path, image.position, image.size, image.description, placeholder=False)
            else:
                slide.add_image(path, description=image.description)
        for sample in [i for i in slide.images if i.is_sample]:
            slide.remove_image(sample)
        for build in spec.builds:
            slide.add_build(**build)
    return deck


def _place_tables(slide: "Slide", spec: SlideSpec) -> None:
    """Lay a slide's tables out side by side, below the title and any body text."""
    if not spec.tables:
        return
    w, h = slide.presentation.size
    margin = w * 0.05
    top = h * (0.24 if spec.title is not None else 0.08)
    if spec.paragraphs:
        top = h * 0.55
    gap = margin / 2
    width = (w - 2 * margin - gap * (len(spec.tables) - 1)) / len(spec.tables)
    for i, table in enumerate(spec.tables):
        row_height = min(h * 0.06, (h - top - margin) / len(table.rows))
        slide.add_table(
            table.rows,
            x=margin + i * (width + gap),
            y=top,
            width=width,
            height=row_height * len(table.rows),
            header_rows=table.header_rows,
        )
