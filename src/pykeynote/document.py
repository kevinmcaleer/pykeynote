"""Read Keynote presentations straight from the .key file, without Keynote."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from .package import Package, PathLike

# Characters Keynote uses inside text storage.
_PARAGRAPH = "\r"  # end of paragraph
_LINE_BREAK = " "  # line break inside a paragraph (shift-return)
_ATTACHMENT = "￼"  # stands in for an inline object, such as an image


@dataclass(frozen=True)
class Paragraph:
    """One paragraph of text. ``level`` is the list indent level, from 0."""

    text: str
    level: int = 0
    bulleted: bool = False


@dataclass(frozen=True)
class Transition:
    """A slide's transition. ``effect`` is ``None`` when there is no transition."""

    effect: Optional[str]
    duration: float
    delay: float
    automatic: bool
    effect_id: str  # Keynote's own name for the effect, e.g. "apple:dissolve"


def _effect_name(effect_id: str) -> Optional[str]:
    if effect_id in ("", "none"):
        return None
    name = effect_id.split(":", 1)[-1]
    if name.startswith("magic-move"):
        return "magic move"
    return name.replace("-", " ")


def _theme_name(identifier: str) -> str:
    """Turn an identifier such as ``"21_BasicWhite"`` into ``"Basic White"``."""
    name = re.sub(r"^\d+_", "", identifier)
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)


class Text:
    """The text in one Keynote text storage."""

    def __init__(self, package: Package, storage: Any):
        self._package = package
        self._storage = storage

    @property
    def raw(self) -> str:
        return "".join(self._storage.text)

    def __str__(self) -> str:
        return "\n".join(p.text for p in self.paragraphs)

    @property
    def paragraphs(self) -> List[Paragraph]:
        raw = self.raw.replace(_ATTACHMENT, "")
        if not raw:
            return []
        out: List[Paragraph] = []
        start = 0
        levels = _ranges(self._storage.table_para_data.entries, lambda e: e.first)
        bullets = _ranges(self._storage.table_list_style.entries, self._is_bulleted)
        for chunk in raw.split(_PARAGRAPH):
            out.append(
                Paragraph(
                    chunk.replace(_LINE_BREAK, "\n"),
                    level=int(_value_at(levels, start) or 0),
                    bulleted=bool(_value_at(bullets, start)),
                )
            )
            start += len(chunk) + 1
        return out

    def _is_bulleted(self, entry: Any) -> Optional[bool]:
        if not entry.HasField("object"):
            return None
        style = self._package.deref(entry.object)
        return bool(getattr(style, "strings", None)) or any(t != 0 for t in getattr(style, "label_types", []))


def _ranges(entries: Any, value: Any) -> List[Tuple[int, Any]]:
    """``(start, value)`` pairs from a Keynote attribute table.

    ``value`` returns ``None`` for an entry that only repeats the previous value.
    """
    out: List[Tuple[int, Any]] = []
    for e in entries:
        v = value(e)
        if v is not None:
            out.append((e.character_index, v))
    return out


def _value_at(ranges: List[Tuple[int, Any]], index: int) -> Any:
    current = None
    for start, value in ranges:
        if start > index:
            break
        current = value
    return current


class Slide:
    """One slide, read from the file."""

    def __init__(self, presentation: "Presentation", node_ref: Any, index: int):
        self.presentation = presentation
        self.index = index
        self._package = presentation.package
        self._node = self._package.deref(node_ref)
        self._slide = self._package.deref(self._node.slide)

    def __repr__(self) -> str:
        return f"<Slide {self.index} {self.layout!r} title={self.title!r}>"

    def _placeholder_text(self, field: str) -> Optional[Text]:
        if not self._slide.HasField(field):
            return None
        ref = getattr(self._slide, field)
        # A placeholder is shown only when it is part of the slide's drawables.
        if ref.identifier not in {r.identifier for r in self._slide.drawables_z_order}:
            return None
        placeholder = self._package.deref(ref)
        return Text(self._package, self._package.deref(placeholder.super.owned_storage))

    @property
    def title_text(self) -> Optional[Text]:
        return self._placeholder_text("titlePlaceholder")

    @property
    def body_text(self) -> Optional[Text]:
        return self._placeholder_text("bodyPlaceholder")

    @property
    def title(self) -> Optional[str]:
        """Title text, or ``None`` if this slide doesn't show a title."""
        text = self.title_text
        return None if text is None else str(text)

    @property
    def body(self) -> Optional[str]:
        """Body text with one line per paragraph, or ``None`` if this slide doesn't show a body."""
        text = self.body_text
        return None if text is None else str(text)

    @property
    def paragraphs(self) -> List[Paragraph]:
        """Body paragraphs with their indent level and whether they have a bullet."""
        text = self.body_text
        return [] if text is None else text.paragraphs

    @property
    def notes(self) -> str:
        if not self._slide.HasField("note"):
            return ""
        note = self._package.deref(self._slide.note)
        return str(Text(self._package, self._package.deref(note.containedStorage)))

    @property
    def layout(self) -> str:
        """Name of the master slide this slide is based on."""
        return self._package.deref(self._slide.template_slide).name

    @property
    def skipped(self) -> bool:
        return bool(self._node.isSkipped)

    @property
    def transition(self) -> Transition:
        a = self._slide.transition.attributes.animationAttributes
        return Transition(
            effect=_effect_name(a.effect),
            duration=a.duration,
            delay=a.delay,
            automatic=a.is_automatic,
            effect_id=a.effect,
        )

    @property
    def has_builds(self) -> bool:
        return len(self._slide.builds) > 0

    def to_dict(self) -> dict:
        t = self.transition
        return {
            "index": self.index,
            "layout": self.layout,
            "title": self.title,
            "body": self.body,
            "notes": self.notes,
            "skipped": self.skipped,
            "transition": {"effect": t.effect, "duration": t.duration, "delay": t.delay, "automatic": t.automatic},
        }


class Presentation:
    """A Keynote presentation read from a ``.key`` file. Keynote isn't needed."""

    def __init__(self, package: Package, path: Optional[str] = None):
        self.package = package
        self.path = path
        self._show = package.deref(package.get(1).show)

    @classmethod
    def open(cls, path: PathLike) -> "Presentation":
        full = os.path.abspath(os.fspath(path))
        return cls(Package.open(full), full)

    def __repr__(self) -> str:
        return f"<Presentation {os.path.basename(self.path or '')!r} slides={len(self)}>"

    @property
    def slides(self) -> List[Slide]:
        return [Slide(self, ref, i) for i, ref in enumerate(self._show.slideTree.slides)]

    def __len__(self) -> int:
        return len(self._show.slideTree.slides)

    def __getitem__(self, index: int) -> Slide:
        return self.slides[index]

    def __iter__(self):
        return iter(self.slides)

    @property
    def size(self) -> Tuple[int, int]:
        """Slide size in points, ``(width, height)``."""
        return int(self._show.size.width), int(self._show.size.height)

    @property
    def theme(self) -> str:
        """Theme name, e.g. ``"Basic White"``."""
        return _theme_name(self._show_theme.super.theme_identifier)

    @property
    def _show_theme(self) -> Any:
        return self.package.deref(self._show.theme)

    @property
    def layouts(self) -> List[str]:
        """Names of the master slides in this presentation's theme, in order."""
        p = self.package
        return [p.deref(p.deref(ref).slide).name for ref in self._show_theme.templates]

    def to_markdown(self) -> str:
        from .markdown import to_markdown

        return to_markdown(self)

    def save(self, path: PathLike) -> None:
        """Write the presentation to ``path`` as a ``.key`` file."""
        self.package.save(path)
