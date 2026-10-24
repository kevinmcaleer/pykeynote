"""Read Keynote presentations straight from the .key file, without Keynote."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Sequence, Tuple, Union

from . import builds as _builds
from . import charts as _charts
from . import tables as _tables
from . import drawables as _drawables
from . import media as _media
from . import movies as _movies
from . import slides
from .builds import Build
from .charts import Chart
from .drawables import Color, Drawable, Shape
from .media import Image, ImageSource
from .movies import MediaSource, Movie
from .tables import Table
from .package import Package, PathLike, remap_references
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

    @property
    def builds(self) -> List[Build]:
        """The slide's build animations, in the order they were added."""
        return _builds.read_builds(self)

    def add_build(
        self,
        target: Union[str, int, Drawable] = "body",
        effect: str = "dissolve",
        delivery: Optional[str] = None,
        duration: float = 1.0,
        kind: str = "in",
    ) -> Build:
        """Animate ``target`` ("title", "body", a shape, table or chart, or its identifier) onto the slide.

        ``delivery`` is "all at once" or "by bullet" (also "by paragraph");
        it defaults to "by bullet" for a body with several paragraphs. Each
        build plays after the ones added before it, one click per step.
        ``effect`` is a build effect such as "dissolve" or "move in", or
        Keynote's own id such as "apple:dissolve character".
        """
        return _builds.add_build(self, target, effect, delivery, duration, kind)

    def clear_builds(self) -> None:
        """Remove every build from the slide."""
        _builds.clear_builds(self)

    # --- shapes, tables and charts ---------------------------------------------

    @property
    def drawables(self) -> List[Drawable]:
        """Shapes, text boxes, tables and charts on the slide, back to front (not the title or body)."""
        return _drawables.drawables_of(self)

    @property
    def shapes(self) -> List[Shape]:
        """Shapes and text boxes."""
        return [d for d in self.drawables if isinstance(d, Shape)]

    @property
    def tables(self) -> List[Table]:
        return [d for d in self.drawables if isinstance(d, Table)]

    @property
    def charts(self) -> List[Chart]:
        return [d for d in self.drawables if isinstance(d, Chart)]

    def _default_frame(self, width: Optional[float], height: Optional[float], x: Optional[float], y: Optional[float], w0: float, h0: float) -> Tuple[float, float, float, float]:
        sw, sh = self.presentation.size
        width = w0 if width is None else width
        height = h0 if height is None else height
        x = (sw - width) / 2 if x is None else x
        y = (sh - height) / 2 if y is None else y
        return float(x), float(y), float(width), float(height)

    def add_shape(
        self,
        kind: str = "rectangle",
        x: Optional[float] = None,
        y: Optional[float] = None,
        width: Optional[float] = None,
        height: Optional[float] = None,
        text: Union[None, str, Iterable[ParagraphInput]] = None,
        fill: Optional[Color] = None,
        style: int = 0,
    ) -> Shape:
        """Add a shape, in the middle of the slide unless ``x`` and ``y`` are given.

        ``kind`` is one of :data:`pykeynote.drawables.SHAPE_KINDS`, such as
        ``"rectangle"``, ``"rounded rectangle"``, ``"oval"``, ``"triangle"``,
        ``"star"`` or ``"arrow"``. ``style`` picks one of the theme's six shape
        styles (0 to 5); ``fill`` overrides its colour, e.g. ``"#3366ff"``.
        Positions and sizes are in points from the slide's top left.
        """
        x, y, width, height = self._default_frame(width, height, x, y, 400, 300)
        return _drawables.add_shape(self, kind, x, y, width, height, text=text, style=style, fill=fill)

    def add_text_box(
        self,
        text: Union[str, Iterable[ParagraphInput]],
        x: Optional[float] = None,
        y: Optional[float] = None,
        width: Optional[float] = None,
        height: Optional[float] = None,
    ) -> Shape:
        """Add a text box in the theme's text box style."""
        x, y, width, height = self._default_frame(width, height, x, y, 600, 80)
        return _drawables.add_shape(self, "text box", x, y, width, height, text=text)

    def add_chart(
        self,
        chart_type: str,
        rows: Sequence[Sequence[Optional[float]]],
        row_names: Sequence[str],
        column_names: Sequence[str],
        x: Optional[float] = None,
        y: Optional[float] = None,
        width: Optional[float] = None,
        height: Optional[float] = None,
        style: int = 0,
        series_by: Optional[str] = None,
        legend: Optional[bool] = None,
    ) -> Chart:
        """Add a chart of ``rows`` of values, one list per row name.

        ``chart_type`` is one of :data:`pykeynote.charts.CHART_TYPES`:
        ``"column"``, ``"bar"``, ``"line"``, ``"area"``, ``"pie"``,
        ``"donut"``, their ``"stacked"`` forms or ``"scatter"``. Each row is a
        data series unless ``series_by="column"``, which is the default for
        pies and donuts: Keynote draws a pie from the first value of each
        series, so the first row's values become the slices. Pies are kept
        square. ``style`` picks one of the theme's six chart styles; the
        legend shows when there is more than one series unless ``legend`` says.
        """
        x, y, width, height = self._default_frame(width, height, x, y, 900, 640)
        return _charts.add_chart(
            self, chart_type, rows, row_names, column_names, x, y, width, height, style=style, series_by=series_by, legend=legend
        )

    def add_table(
        self,
        rows: Sequence[Sequence[Any]],
        x: Optional[float] = None,
        y: Optional[float] = None,
        width: Optional[float] = None,
        height: Optional[float] = None,
        header_rows: int = 1,
        header_columns: int = 0,
        style: int = 0,
        name: Optional[str] = None,
    ) -> Table:
        """Add a table of ``rows``: lists of text, numbers, True/False or None for an empty cell.

        The first ``header_rows`` rows (and ``header_columns`` columns) are
        headers. ``style`` picks one of the theme's six table styles. The
        table is centred unless ``x`` and ``y`` are given; each row is 64
        points high unless ``height`` is given.
        """
        n_rows = len(rows)
        n_cols = max((len(r) for r in rows), default=0)
        sw, sh = self.size_of_slide
        w = width if width is not None else min(sw - 120, 300.0 * max(n_cols, 1))
        h = height if height is not None else 64.0 * max(n_rows, 1)
        x = (sw - w) / 2 if x is None else x
        y = (sh - h) / 2 if y is None else y
        return _tables.add_table(self, rows, x, y, w, h, header_rows=header_rows, header_columns=header_columns, style=style, name=name)

    @property
    def size_of_slide(self) -> Tuple[int, int]:
        return self.presentation.size

    def delete_drawable(self, drawable: Drawable) -> None:
        """Remove a shape, text box, table or chart from the slide."""
        if drawable.slide._slide_id != self._slide_id:
            raise ValueError("that drawable is on another slide")
        if any(b.target == drawable.identifier for b in self.builds):
            raise ValueError("remove the drawable's builds first (clear_builds)")
        _drawables.delete_drawable(self, drawable)

    @property
    def images(self) -> List[Image]:
        """The slide's images, back to front, including media placeholders."""
        return _media.read_images(self)

    @property
    def placeholders(self) -> List[Image]:
        """The layout's media placeholders on this slide, left to right and top to bottom."""
        return _media.placeholders(self)

    def add_image(
        self,
        source: ImageSource,
        position: Optional[Tuple[float, float]] = None,
        size: Optional[Tuple[Optional[float], Optional[float]]] = None,
        description: Optional[str] = None,
        placeholder: Union[None, bool, str] = None,
        name: Optional[str] = None,
    ) -> Image:
        """Add a PNG, JPEG or GIF image, from a file path or bytes.

        With no ``position`` or ``size``, the image fills the slide's first
        media placeholder that still shows the theme's sample photo, cropped
        to it as Keynote does. Otherwise, or with ``placeholder=False``, it
        goes on top of everything else: at ``position`` (top left, in
        points), ``size`` wide and high (give one as ``None`` to keep the
        picture's shape), and centred if no position is given.
        ``placeholder`` can also name a placeholder, e.g. ``"Media-2"``.
        ``description`` is the accessibility description (alt text).
        ``name`` is the file name to store bytes under.
        """
        return _media.add_image(self, source, position, size, description, placeholder, name)

    def replace_image(
        self,
        image: Union[Image, int, str],
        source: ImageSource,
        description: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Image:
        """Put a new picture in place of ``image``: an :class:`Image`, its index in :attr:`images`, or a placeholder tag.

        A cropped image (such as a placeholder) keeps its crop, with the new
        picture scaled to cover it. Otherwise the picture fits inside the old one's frame.
        """
        return _media.replace_image(self, image, source, description, name)

    def remove_image(self, image: Union[Image, int, str]) -> None:
        """Delete an image, and any builds on it."""
        _media.remove_image(self, image)

    @property
    def movies(self) -> List[Movie]:
        """The slide's videos and sounds, back to front."""
        return _movies.read_movies(self)

    def add_movie(
        self,
        source: MediaSource,
        position: Optional[Tuple[float, float]] = None,
        size: Optional[Tuple[Optional[float], Optional[float]]] = None,
        description: Optional[str] = None,
        placeholder: Union[None, bool, str] = None,
        poster: Optional[ImageSource] = None,
        loop: str = "none",
        volume: float = 1.0,
        name: Optional[str] = None,
    ) -> Movie:
        """Add a video or a sound: an MPEG-4 or QuickTime file (.mp4, .m4v, .mov or .m4a), from a path or bytes.

        A video goes where an image would (see :meth:`add_image`): into the
        first media placeholder still showing the theme's sample photo,
        fitted inside it, unless ``position`` or ``size`` is given. A sound
        has no picture, so it sits in the middle of the slide unless
        ``position`` says. ``poster`` is the picture shown before a video
        plays (black otherwise). ``loop`` is ``"none"``, ``"repeat"`` or
        ``"back and forth"``, and ``volume`` goes from 0 to 1.
        """
        return _movies.add_movie(self, source, position, size, description, placeholder, poster, loop, volume, name)

    def add_audio(
        self,
        source: MediaSource,
        position: Optional[Tuple[float, float]] = None,
        description: Optional[str] = None,
        loop: str = "none",
        volume: float = 1.0,
        name: Optional[str] = None,
    ) -> Movie:
        """Add a sound: an .m4a file, or another MPEG-4 or QuickTime file with no picture. See :meth:`add_movie`."""
        movie = _movies.add_movie(self, source, position, None, description, False, None, loop, volume, name)
        if not movie.audio_only:
            self.remove_movie(movie)
            raise ValueError("that file has a picture: add it with add_movie")
        return movie

    def remove_movie(self, movie: Union[Movie, int, str]) -> None:
        """Delete a video or sound (a :class:`Movie`, its index in :attr:`movies`, or a placeholder tag), and any builds on it."""
        _movies.remove_movie(self, movie)

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
            "drawables": [d.to_dict() for d in self.drawables],
            "images": [
                {
                    "position": list(i.position),
                    "size": list(i.size),
                    "description": i.description,
                    "placeholder": i.placeholder,
                    "filename": i.filename,
                }
                for i in self.images
            ],
            "movies": [
                {
                    "position": list(m.position),
                    "size": list(m.size),
                    "duration": m.duration,
                    "audio_only": m.audio_only,
                    "description": m.description,
                    "placeholder": m.placeholder,
                    "filename": m.filename,
                }
                for m in self.movies
            ],
        }


def _unshare_drawables(original: "Slide", copy: "Slide") -> None:
    """Give a duplicated slide its own copies of the original's tables and charts.

    Copying a slide's file copies its shapes, but tables and charts keep
    objects in other files, which the copy would otherwise share.
    """
    from .clone import Importer
    from .drawables import add_external_reference, component_id_of, remove_external_reference

    pairs = [(a, b) for a, b in zip(original.drawables, copy.drawables) if isinstance(a, (Table, Chart))]
    if not pairs:
        return
    p = copy._package
    importer = Importer(p, p)
    s = copy._slide
    for old, alias in pairs:
        if isinstance(old, Table):
            new = _tables.copy_table(importer, old.identifier, original._slide_id, copy)
        else:
            new = _charts.copy_chart(importer, old.identifier, original._slide_id, copy)
        remap_references(s, {alias.identifier: new.identifier})  # drawables, z-order and the like
        for build_ref in s.builds:
            build = p.deref(build_ref)
            if build.drawable.identifier == alias.identifier:
                build.drawable.identifier = new.identifier
                p.mark_changed(build_ref.identifier)
        p.remove_object_reference(copy._slide_id, alias.identifier)
        p.add_object_reference(copy._slide_id, new.identifier)
        component = p.component(component_id_of(p, copy._slide_id))
        remove_external_reference(p, component, alias.identifier)
        add_external_reference(p, component, new.identifier)
        if alias.identifier != old.identifier:
            # The chart itself was copied with the slide's file: drop that copy and what only it owns.
            from .clone import owned_objects, remove_objects

            slide_file = p.file_of(copy._slide_id)
            remove_objects(p, [i for i in owned_objects(p, alias.identifier, {copy._slide_id}) if p.file_of(i) == slide_file])
    p.mark_changed(copy._slide_id)


TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")


# Bundled templates are named "<theme>-<aspect>.key", e.g. "basic-white-16x9.key".
ASPECTS = ("16:9", "4:3")


def _template_file(theme: str, aspect: str) -> str:
    return theme.strip().lower().replace(" ", "-") + "-" + aspect.replace(":", "x") + ".key"


def _bundled() -> List[Tuple[str, str]]:
    out = []
    for f in sorted(os.listdir(TEMPLATES_DIR)):
        if f.endswith(".key"):
            name, _, aspect = f[:-4].rpartition("-")
            out.append((name.replace("-", " ").title(), aspect.replace("x", ":")))
    return out


def themes() -> List[str]:
    """Names of the themes bundled with pykeynote, for :meth:`Presentation.new`."""
    return sorted({name for name, _ in _bundled()})


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
    def new(cls, theme: str = "Basic White", aspect: str = "16:9") -> "Presentation":
        """A new, empty presentation in one of the bundled themes (see :func:`themes`).

        ``aspect`` is ``"16:9"`` (1920 x 1080, Keynote's Wide) or ``"4:3"``
        (1024 x 768, Keynote's Standard).
        """
        if aspect not in ASPECTS:
            raise ValueError(f"aspect must be one of {', '.join(ASPECTS)}, not {aspect!r}")
        path = os.path.join(TEMPLATES_DIR, _template_file(theme, aspect))
        if not os.path.exists(path):
            available = ", ".join(f"{n} ({a})" for n, a in _bundled())
            raise ValueError(f"no bundled theme {theme!r} at {aspect}; available: {available}")
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
        slide = self.slides[index]
        # Tables and charts keep objects outside the slide's own file; remove those first.
        for drawable in slide.drawables:
            if isinstance(drawable, (Table, Chart)):
                _drawables.delete_drawable(slide, drawable)
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
        copy = self.slides[to]
        original = Slide(self, type(self._show.slideTree.slides[0])(identifier=node_id), -1)
        _unshare_drawables(original, copy)
        return copy

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

    @theme.setter
    def theme(self, name: str) -> None:
        self.apply_theme(name)

    @property
    def _show_theme(self) -> Any:
        return self.package.deref(self._show.theme)

    @property
    def layouts(self) -> List[str]:
        """Names of the master slides in this presentation's theme, in order."""
        p = self.package
        return [p.deref(p.deref(ref).slide).name for ref in self._show_theme.templates]

    def _layout_shows(self) -> dict:
        """For each layout this presentation has a slide for, whether it shows ``(title, body)``."""
        shows: dict = {}
        for ref in self._show.slideTree.slides:
            slide = Slide(self, ref, -1)
            shows.setdefault(slide.layout, (slide.title is not None, slide.body is not None))
        return shows

    def match_layout(self, layout: str, title: bool = False, body: bool = False) -> str:
        """The layout here that best stands in for ``layout`` from another theme.

        A layout with the same name is used when it shows a title and a
        body wherever they're needed (``title`` and ``body`` say which are).
        Otherwise the layout is picked by what it shows: "Title & Bullets"
        for a title and body, "Bullets" for a body alone, "Title Only" for a
        title alone, and "Blank" for neither.
        """
        shows = self._layout_shows()

        def fits(name: str) -> bool:
            if name not in shows:
                return False
            has_title, has_body = shows[name]
            return (has_title or not title) and (has_body or not body)

        if fits(layout):
            return layout
        fallbacks = {
            (True, True): ["Title & Bullets", "Title, Bullets & Photo", "Title"],
            (False, True): ["Bullets", "Statement", "Title & Bullets"],
            (True, False): ["Title Only", "Section", "Title"],
            (False, False): ["Blank", "Title Only"],
        }[(title, body)]
        for name in fallbacks + [n for n in self.layouts if n in shows]:
            if fits(name):
                return name
        raise ValueError(f"no layout in the {self.theme!r} theme can stand in for {layout!r}")

    def apply_theme(
        self,
        theme: str,
        aspect: Optional[str] = None,
        layouts: Optional[dict] = None,
    ) -> None:
        """Switch to one of the bundled themes (see :func:`themes`), keeping the content.

        Each slide is rebuilt on the new theme's layout with the same name,
        or the closest match (see :meth:`match_layout`), and keeps its title
        and body text with indent levels, presenter notes, transition,
        skipped flag, and builds on its title and body. ``layouts`` maps old
        layout names to new ones where the default choice isn't wanted, e.g.
        ``{"Quote": "Statement"}``. Images, shapes, text boxes and text
        formatting that differs from the layout's own are not carried over.

        ``aspect`` is ``"16:9"`` or ``"4:3"``; it defaults to whichever is
        closer to the current slide size.
        """
        if aspect is None:
            width, height = self.size
            aspect = "4:3" if width / height < (16 / 9 + 4 / 3) / 2 else "16:9"
        layouts = layouts or {}
        target = Presentation.new(theme, aspect)
        for old in self.slides:
            title, body = old.title_text, old.body_text
            wanted = layouts.get(old.layout)
            if wanted is not None and wanted not in target.layouts:
                raise ValueError(f"no {wanted!r} layout in the {theme!r} theme; layouts: {', '.join(target.layouts)}")
            layout = wanted or target.match_layout(old.layout, title is not None, body is not None)
            new = target.add_slide(layout)
            if title is not None and new.title_text is not None:
                new.title_text.set_paragraphs(title.paragraphs or [""])
            if body is not None and new.body_text is not None:
                new.body_text.set_paragraphs(body.paragraphs or [""])
            new.notes = old.notes
            t = old.transition
            new.set_transition(t.effect_id, t.duration, t.delay, t.automatic)
            new.skipped = old.skipped
            for b in old.builds:
                if b.target not in ("title", "body") or getattr(new, f"{b.target}_text") is None:
                    continue
                delivery = b.delivery.lower() if b.delivery.lower() in _builds._DELIVERY_NAMES else None
                new.add_build(b.target, b.effect_id, delivery, b.duration, b.kind)
            new._touched()
        self.package = target.package
        self._show_id = target._show_id
        self._show = target._show
        self._prototypes = target._prototypes

    def _all_tables(self) -> List[Table]:
        return [t for s in self.slides for t in s.tables]

    def to_markdown(self, image_dir: Optional[PathLike] = None) -> str:
        """The presentation as Markdown. With ``image_dir``, images are saved there and linked by that path."""
        from .markdown import to_markdown

        return to_markdown(self, None if image_dir is None else os.fspath(image_dir))

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
