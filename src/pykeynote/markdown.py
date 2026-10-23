"""Convert a presentation to Markdown.

Each slide becomes a block, and blocks are separated by ``---``::

    <!-- layout: Title & Bullets -->
    <!-- transition: dissolve 1.5s -->
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
from typing import TYPE_CHECKING, List

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
