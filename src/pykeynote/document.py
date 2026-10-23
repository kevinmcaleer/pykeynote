"""Read Keynote presentations straight from the .key file, without Keynote."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Tuple, Union

from .package import Package, PathLike
from .text import Paragraph, ParagraphInput, Text

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


class Slide:
    """One slide, read from the file."""

    def __init__(self, presentation: "Presentation", node_ref: Any, index: int):
        self.presentation = presentation
        self.index = index
        self._package = presentation.package
        self._node_id = node_ref.identifier
        self._node = self._package.deref(node_ref)
        self._slide_id = self._node.slide.identifier
        self._slide = self._package.get(self._slide_id)

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
        return Text(self._package, placeholder.super.owned_storage.identifier)

    def _set_placeholder_text(self, field: str, value: Union[str, Iterable[ParagraphInput]]) -> None:
        text = self._placeholder_text(field)
        if text is None:
            what = "title" if field == "titlePlaceholder" else "body"
            raise ValueError(f"the {self.layout!r} layout doesn't show a {what} on slide {self.index}")
        text.set_paragraphs(value.split("\n") if isinstance(value, str) else value)
        self._touched()

    def _touched(self) -> None:
        # Keynote redraws thumbnails flagged as dirty when it opens the file.
        if not self._node.thumbnailsAreDirty:
            self._node.thumbnailsAreDirty = True
            self._package.mark_changed(self._node_id)

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

    @title.setter
    def title(self, value: str) -> None:
        self._set_placeholder_text("titlePlaceholder", value)

    @property
    def body(self) -> Optional[str]:
        """Body text with one line per paragraph, or ``None`` if this slide doesn't show a body.

        Assign a string with one line per paragraph, or a list of strings or
        :class:`Paragraph` objects to set indent levels too.
        """
        text = self.body_text
        return None if text is None else str(text)

    @body.setter
    def body(self, value: Union[str, Iterable[ParagraphInput]]) -> None:
        self._set_placeholder_text("bodyPlaceholder", value)

    @property
    def paragraphs(self) -> List[Paragraph]:
        """Body paragraphs with their indent level and whether they have a bullet."""
        text = self.body_text
        return [] if text is None else text.paragraphs

    def _notes_text(self) -> Optional[Text]:
        if not self._slide.HasField("note"):
            return None
        note = self._package.deref(self._slide.note)
        return Text(self._package, note.containedStorage.identifier)

    @property
    def notes(self) -> str:
        text = self._notes_text()
        return "" if text is None else str(text)

    @notes.setter
    def notes(self, value: str) -> None:
        text = self._notes_text()
        if text is None:
            raise ValueError(f"slide {self.index} has no notes storage")
        text.set_paragraphs(value.split("\n"))

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

    def save(self, path: Optional[PathLike] = None) -> None:
        """Write the presentation as a ``.key`` file, to ``path`` or back where it came from."""
        target = path if path is not None else self.path
        if target is None:
            raise ValueError("no path to save to")
        self.package.save(target)
