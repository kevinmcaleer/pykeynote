"""Convert a presentation to Markdown.

Each slide becomes a block, and blocks are separated by ``---``::

    <!-- layout: Title & Bullets -->
    <!-- transition: dissolve 1.5s -->
    <!-- build: body, dissolve, by bullet, 1s -->
    # Slide title

    - A bullet
      - An indented bullet

    A paragraph without a bullet

    ???
    Presenter notes

Slide settings go in HTML comments, so the Markdown still renders cleanly
elsewhere. Notes follow a line holding only ``???``, as in remark.js.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional

from .text import Paragraph

if TYPE_CHECKING:
    from .document import Presentation, Slide

SLIDE_SEPARATOR = "---"
NOTES_MARKER = "???"

# A plain paragraph starting like this would read as Markdown syntax.
_NEEDS_ESCAPE = re.compile(r"^(#|[-*+] |\d+[.)] |>|---|\?\?\?|<!--)")


def _fmt_seconds(value: float) -> str:
    return f"{value:g}s"


def slide_to_markdown(slide: "Slide") -> str:
    lines: List[str] = [f"<!-- layout: {slide.layout} -->"]
    t = slide.transition
    if t.effect:
        lines.append(f"<!-- transition: {t.effect} {_fmt_seconds(t.duration)} -->")
    if slide.skipped:
        lines.append("<!-- skipped -->")
    for b in slide.builds:
        if isinstance(b.target, str):
            delivery = "by bullet" if b.delivery == "By Paragraph" else b.delivery.lower()
            kind = "" if b.kind == "in" else f", {b.kind}"
            lines.append(f"<!-- build: {b.target}, {b.effect}, {delivery}, {_fmt_seconds(b.duration)}{kind} -->")

    if slide.title is not None and slide.title.strip():
        lines.append("# " + " ".join(slide.title.split()))

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

    notes = slide.notes.strip()
    if notes:
        lines.extend(["", NOTES_MARKER, notes])
    return "\n".join(lines) + "\n"


def to_markdown(presentation: "Presentation") -> str:
    return f"\n{SLIDE_SEPARATOR}\n\n".join(slide_to_markdown(s) for s in presentation.slides)


# --- Markdown to a presentation -------------------------------------------------

_COMMENT = re.compile(r"^<!--\s*(.*?)\s*-->$")
_HEADING = re.compile(r"^#{1,2}\s+(.*)$")
_BULLET = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(.*)$")
_TRANSITION = re.compile(r"^(.*?)(?:\s+([\d.]+)\s*s)?$")


@dataclass
class SlideSpec:
    """One slide parsed from Markdown, before it is added to a deck."""

    layout: Optional[str] = None
    title: Optional[str] = None
    paragraphs: List[Paragraph] = field(default_factory=list)
    notes: str = ""
    transition: Optional[str] = None
    transition_duration: Optional[float] = None
    skipped: bool = False
    builds: List[dict] = field(default_factory=list)

    def default_layout(self) -> str:
        bulleted = any(p.bulleted for p in self.paragraphs)
        if self.title and self.paragraphs:
            return "Title & Bullets" if bulleted else "Title"
        if self.title:
            return "Title Only"
        if self.paragraphs:
            return "Bullets" if bulleted else "Statement"
        return "Blank"


def _clean(text: str) -> str:
    text = text.strip().replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    return text[1:] if text.startswith("\\") else text


def _parse_build(value: str) -> dict:
    """Read ``target, effect[, delivery][, 1.5s][, in|out]`` from a build comment."""
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if len(parts) < 2:
        raise ValueError(f"a build needs at least a target and an effect: {value!r}")
    build = {"target": parts[0].lower(), "effect": parts[1]}
    for part in parts[2:]:
        low = part.lower()
        if re.fullmatch(r"[\d.]+\s*s", low):
            build["duration"] = float(low.rstrip("s").strip())
        elif low in ("in", "out"):
            build["kind"] = low
        else:
            build["delivery"] = low
    return build


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

        def flush() -> None:
            if pending:
                spec.paragraphs.append(Paragraph(_clean(" ".join(s.strip() for s in pending)), 0, False))
                pending.clear()

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
                elif key == "skipped":
                    spec.skipped = value.lower() not in ("false", "no", "0")
                elif key == "build":
                    spec.builds.append(_parse_build(value))
                continue
            heading = _HEADING.match(stripped)
            if heading and spec.title is None and not spec.paragraphs and not pending:
                spec.title = _clean(heading.group(1))
                continue
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


def from_markdown(text: str, theme: str = "Basic White", aspect: str = "16:9") -> "Presentation":
    """Build a new presentation from Markdown in the :func:`to_markdown` format.

    A slide without a ``layout`` comment gets one from its content: title and
    bullets give "Title & Bullets", a title alone "Title Only", and so on.
    """
    from .document import Presentation

    deck = Presentation.new(theme, aspect)
    available = set(deck.layouts)
    for spec in parse_markdown(text):
        layout = spec.layout or spec.default_layout()
        if layout not in available:
            layout = "Title & Bullets"
        slide = deck.add_slide(layout)
        if spec.title is not None:
            if slide.title is None:
                raise ValueError(f"the {layout!r} layout doesn't show a title, for {spec.title!r}")
            slide.title = spec.title
        if spec.paragraphs:
            if slide.body is None:
                raise ValueError(f"the {layout!r} layout doesn't show a body, for {spec.paragraphs[0].text!r}")
            slide.body = spec.paragraphs
        if spec.notes:
            slide.notes = spec.notes
        if spec.transition:
            slide.set_transition(spec.transition, spec.transition_duration)
        if spec.skipped:
            slide.skipped = True
        for build in spec.builds:
            slide.add_build(**build)
    return deck
