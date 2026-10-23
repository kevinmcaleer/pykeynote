"""Read Keynote presentations straight from the .key file, without Keynote."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Tuple, Union

from . import slides
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


def _effect_id(name: Optional[str]) -> str:
    if name is None or name.strip().lower() in ("", "none", "no transition"):
        return "none"
    if ":" in name:
        return name
    key = name.strip().lower().replace("_", " ").replace("-", " ")
    if key == "magic move":
        return "apple:magic-move-implied-motion-path"
    return "apple:" + key.replace(" ", "-")


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

    @skipped.setter
    def skipped(self, value: bool) -> None:
        self._node.isSkipped = bool(value)
        self._package.mark_changed(self._node_id)

    def set_transition(
        self,
        effect: Optional[str],
        duration: Optional[float] = None,
        delay: Optional[float] = None,
        automatic: Optional[bool] = None,
    ) -> None:
        """Set the transition into the next slide, e.g. ``set_transition("dissolve", 1.5)``.

        ``effect`` is a name such as ``"dissolve"``, ``"push"`` or ``"magic
        move"``, Keynote's own id such as ``"apple:dissolve"``, or ``None`` to
        remove the transition. Dissolve, push and magic move are checked
        against real Keynote files; other names follow the same pattern.
        """
        attrs = self._slide.transition.attributes
        a = attrs.animationAttributes
        effect_id = _effect_id(effect)
        a.effect = effect_id
        for field in ("custom_magic_move_fade_unmatched_objects", "custom_timing_curve", "custom_text_delivery_type"):
            attrs.ClearField(field)
        if effect_id.startswith("apple:magic-move"):
            # What Keynote 14.5 writes for a default Magic Move.
            attrs.custom_magic_move_fade_unmatched_objects = True
            attrs.custom_timing_curve = attrs.TransitionCustomAttributesTimingCurveTypeEaseInEaseOut
            attrs.custom_text_delivery_type = attrs.TransitionCustomAttributesTextDeliveryTypeByObject
        if duration is not None:
            a.duration = float(duration)
        if delay is not None:
            a.delay = float(delay)
        if automatic is not None:
            a.is_automatic = bool(automatic)
        self._package.mark_changed(self._slide_id)
        self._node.hasTransition = effect_id != "none"
        self._package.mark_changed(self._node_id)

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


TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")


def _template_file(theme: str) -> str:
    return theme.strip().lower().replace(" ", "-") + ".key"


def themes() -> List[str]:
    """Names of the themes bundled with pykeynote, for :meth:`Presentation.new`."""
    names = sorted(f[:-4] for f in os.listdir(TEMPLATES_DIR) if f.endswith(".key"))
    return [n.replace("-", " ").title() for n in names]


def _reparse(package: Package) -> Package:
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(package.to_bytes())) as z:
        return Package({n: z.read(n) for n in z.namelist() if not n.endswith("/")})


class Presentation:
    """A Keynote presentation read from a ``.key`` file. Keynote isn't needed."""

    def __init__(self, package: Package, path: Optional[str] = None):
        self.package = package
        self.path = path
        self._show_id = package.get(1).show.identifier
        self._show = package.get(self._show_id)
        # Slides kept only as models for add_slide(); hidden, and left out on save.
        self._prototypes: set = set()

    @classmethod
    def open(cls, path: PathLike) -> "Presentation":
        full = os.path.abspath(os.fspath(path))
        return cls(Package.open(full), full)

    @classmethod
    def new(cls, theme: str = "Basic White") -> "Presentation":
        """A new, empty presentation in one of the bundled themes (see :func:`themes`)."""
        path = os.path.join(TEMPLATES_DIR, _template_file(theme))
        if not os.path.exists(path):
            raise ValueError(f"no bundled theme {theme!r}; choose from {', '.join(themes())}")
        pres = cls(Package.open(path))
        pres._prototypes = set(pres._node_ids(include_prototypes=True))
        return pres

    def _node_ids(self, include_prototypes: bool = False) -> List[int]:
        ids = [ref.identifier for ref in self._show.slideTree.slides]
        return ids if include_prototypes else [i for i in ids if i not in self._prototypes]

    def _tree_index(self, index: int) -> int:
        """Position in the full slide tree of the visible slide at ``index``."""
        visible = self._node_ids()
        return self._node_ids(include_prototypes=True).index(visible[index])

    def __repr__(self) -> str:
        return f"<Presentation {os.path.basename(self.path or '')!r} slides={len(self)}>"

    @property
    def slides(self) -> List[Slide]:
        refs = [r for r in self._show.slideTree.slides if r.identifier not in self._prototypes]
        return [Slide(self, ref, i) for i, ref in enumerate(refs)]

    def __len__(self) -> int:
        return len(self._node_ids())

    # --- changing the slide list ---------------------------------------------

    def _check_index(self, index: int, allow_end: bool = False) -> int:
        count = len(self)
        if index < 0:
            index += count + (1 if allow_end else 0)
        if not 0 <= index < count + (1 if allow_end else 0):
            raise IndexError(f"slide index {index} out of range for {count} slides")
        return index

    def move_slide(self, old: int, new: int) -> None:
        """Move the slide at ``old`` so it ends up at ``new``."""
        old, new = self._check_index(old), self._check_index(new)
        visible = self._node_ids()
        node = visible.pop(old)
        visible.insert(new, node)
        full = self._node_ids(include_prototypes=True)
        prototypes = [i for i in full if i in self._prototypes]
        slides.set_tree(self.package, self._show_id, prototypes + visible)

    def delete_slide(self, index: int) -> None:
        index = self._check_index(index)
        slides.delete_slide(self.package, self._show_id, self._tree_index(index))

    def duplicate_slide(self, index: int, to: Optional[int] = None) -> Slide:
        """Copy the slide at ``index``. The copy goes right after it unless ``to`` is given."""
        index = self._check_index(index)
        to = index + 1 if to is None else self._check_index(to, allow_end=True)
        return self._copy_node(self._node_ids()[index], to)

    def _copy_node(self, node_id: int, to: int) -> Slide:
        full = self._node_ids(include_prototypes=True)
        visible = self._node_ids()
        tree_to = len(full) if to >= len(visible) else full.index(visible[to])
        slides.duplicate_slide(self.package, self._show_id, full.index(node_id), tree_to)
        return self.slides[to]

    def add_slide(
        self,
        layout: str = "Title & Bullets",
        title: Optional[str] = None,
        body: Union[None, str, Iterable[ParagraphInput]] = None,
        notes: Optional[str] = None,
        index: Optional[int] = None,
    ) -> Slide:
        """Add a slide with the given layout, at the end unless ``index`` is given.

        The new slide is copied from an existing slide with that layout, so
        it keeps that slide's look. Presentations made with :meth:`new` have
        one of every layout to copy from. For other presentations, at least
        one slide must already use the layout.
        """
        to = len(self) if index is None else self._check_index(index, allow_end=True)
        source = self._find_layout(layout)
        slide = self._copy_node(source, to)
        if slide.title is not None:
            slide.title = title or ""
        if slide.body is not None:
            slide.body = body if body is not None else ""
        if notes is not None or slide.notes:
            slide.notes = notes or ""
        if title is not None and slide.title is None:
            raise ValueError(f"the {layout!r} layout doesn't show a title")
        if body is not None and slide.body is None:
            raise ValueError(f"the {layout!r} layout doesn't show a body")
        return slide

    def _find_layout(self, layout: str) -> int:
        p = self.package

        def layout_of(node_id: int) -> str:
            slide = p.deref(p.get(node_id).slide)
            return p.deref(slide.template_slide).name

        candidates = [n for n in self._prototypes if layout_of(n) == layout]
        candidates += [n for n in self._node_ids() if layout_of(n) == layout]
        if not candidates:
            raise ValueError(
                f"no slide uses the {layout!r} layout to copy from; layouts here: {', '.join(self.layouts)}"
            )
        return candidates[0]

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
        if not self._node_ids():
            raise ValueError("a presentation needs at least one slide")
        package = self.package
        if self._prototypes:
            # Save a copy without the model slides, so this object can keep adding slides.
            package = _reparse(package)
            show_id = package.get(1).show.identifier
            for node_id in [r.identifier for r in package.get(show_id).slideTree.slides]:
                if node_id in self._prototypes:
                    tree = [r.identifier for r in package.get(show_id).slideTree.slides]
                    slides.delete_slide(package, show_id, tree.index(node_id))
        package.save(target)
        self.path = os.path.abspath(os.fspath(target))
