"""Things drawn on a slide besides its title and body: shapes, text boxes, tables and charts.

A slide lists what it draws in ``KN.SlideArchive.owned_drawables`` and, back
to front, ``drawables_z_order``. A shape or text box is a
``TSWP.ShapeInfoArchive``: a frame, a path for its outline, a shape style
and a text storage. It lives in the slide's own component file, along with
the two empty ``TSD.StandinCaptionArchive`` objects Keynote gives every
drawable for its title and caption.

New shapes use the theme's own styles, found by the names every Keynote
theme gives them (``shape-0-shapestyle`` and so on) in the document
stylesheet's ``identifier_to_style_map``. A shape that refers to an object
in another component, such as a style, needs a matching entry in its
slide component's ``external_references``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Iterable, List, Optional, Sequence, Tuple, Union

from keynote_parser.codec import IWAArchiveSegment, import_version

from .package import METADATA_ID, Package, new_uuid_parts, type_name_of
from .text import ParagraphInput, Text

if TYPE_CHECKING:
    from .document import Slide

STYLESHEET_FILE = "Index/DocumentStylesheet.iwa"

# Message types and versions, as Keynote 14.5 writes them.
SHAPE_INFO = (2011, (1, 0, 5))
STORAGE = (2001, (1, 0, 5))
CAPTION = (3097, (10, 1, 0))
SHAPE_STYLE = (2025, (1, 0, 5))

Color = Union[str, Tuple[float, float, float], Tuple[float, float, float, float]]


def make_header(identifier: int, kind: Tuple[int, Sequence[int]], refs: Iterable[int] = ()) -> Any:
    archive_info = import_version()[2]
    header = archive_info()
    header.identifier = identifier
    info = header.message_infos.add()
    info.type = kind[0]
    info.version.extend(kind[1])
    info.length = 0  # set when the file is encoded
    info.object_references.extend(refs)
    return header


def new_archive(type_name: str) -> Any:
    return import_version()[1][type_name]()


# --- styles -------------------------------------------------------------------


def stylesheet_id(package: Package) -> int:
    return package.component_for_file(STYLESHEET_FILE).identifier


def named_styles(package: Package) -> dict:
    """The theme's styles by their names, e.g. ``"shape-0-shapestyle"``."""
    sheet = package.get(stylesheet_id(package))
    return {e.identifier: e.style.identifier for e in sheet.identifier_to_style_map}


def style_named(package: Package, name: str) -> int:
    styles = named_styles(package)
    if name not in styles:
        raise ValueError(f"this theme has no {name!r} style")
    return styles[name]


def add_variation_style(package: Package, parent_id: int) -> Tuple[int, Any]:
    """A new style based on ``parent_id`` that can override some of its properties.

    This is what Keynote makes when you change one shape's fill, say.
    """
    parent = package.get(parent_id)
    sheet_id = stylesheet_id(package)
    style_id = package.new_identifier()
    style = type(parent)()
    style.super.super.parent.identifier = parent_id
    style.super.super.is_variation = True
    style.super.super.stylesheet.identifier = sheet_id
    style.super.override_count = 0
    package.add_segment(STYLESHEET_FILE, IWAArchiveSegment(make_header(style_id, SHAPE_STYLE, [parent_id]), [style]))
    sheet = package.get(sheet_id)
    sheet.styles.add().identifier = style_id
    for entry in sheet.parent_to_children_style_map:
        if entry.parent.identifier == parent_id:
            entry.children.add().identifier = style_id
            break
    else:
        entry = sheet.parent_to_children_style_map.add()
        entry.parent.identifier = parent_id
        entry.children.add().identifier = style_id
    package.add_object_reference(sheet_id, style_id)
    package.mark_changed(sheet_id)
    component = package.component_for_file(STYLESHEET_FILE)
    _add_uuid(component, style_id)
    return style_id, style


_NAMED_COLORS = {
    "black": (0, 0, 0),
    "white": (1, 1, 1),
    "red": (1, 0.23, 0.19),
    "orange": (1, 0.58, 0),
    "yellow": (1, 0.8, 0),
    "green": (0.2, 0.78, 0.35),
    "blue": (0, 0.48, 1),
    "purple": (0.69, 0.32, 0.87),
    "pink": (1, 0.18, 0.33),
    "gray": (0.56, 0.56, 0.58),
    "grey": (0.56, 0.56, 0.58),
}


def parse_color(value: Color) -> Tuple[float, float, float, float]:
    """``"#3366ff"``, ``"#36f"``, a name such as ``"blue"``, or an (r, g, b[, a]) tuple of 0-1 floats."""
    if isinstance(value, str):
        v = value.strip().lower()
        if v in _NAMED_COLORS:
            return (*map(float, _NAMED_COLORS[v]), 1.0)
        if v.startswith("#"):
            v = v[1:]
            if len(v) in (3, 4):
                v = "".join(c * 2 for c in v)
            if len(v) in (6, 8) and all(c in "0123456789abcdef" for c in v):
                parts = [int(v[i : i + 2], 16) / 255 for i in range(0, len(v), 2)]
                return (parts[0], parts[1], parts[2], parts[3] if len(parts) == 4 else 1.0)
        raise ValueError(f"not a colour: {value!r}")
    parts = [float(x) for x in value]
    if len(parts) not in (3, 4) or not all(0 <= x <= 1 for x in parts):
        raise ValueError(f"a colour tuple needs 3 or 4 values from 0 to 1, not {value!r}")
    return (parts[0], parts[1], parts[2], parts[3] if len(parts) == 4 else 1.0)


def color_hex(color: Any) -> str:
    return "#" + "".join(f"{round(c * 255):02x}" for c in (color.r, color.g, color.b))


def _set_color(message: Any, rgba: Tuple[float, float, float, float]) -> None:
    message.model = message.rgb
    message.r, message.g, message.b, message.a = rgba
    message.rgbspace = message.srgb


# --- components ---------------------------------------------------------------


def _add_uuid(component: Any, identifier: int) -> None:
    entry = component.object_uuid_map_entries.add()
    entry.identifier = identifier
    entry.uuid.lower, entry.uuid.upper = new_uuid_parts()


def component_id_of(package: Package, identifier: int) -> int:
    return package.component_for_file(package.file_of(identifier)).identifier


def add_external_reference(package: Package, component: Any, target: int, weak: bool = False) -> None:
    """Record that ``component`` refers to ``target``, an object in another component."""
    target_component = component_id_of(package, target)
    if target_component == component.identifier:
        return
    for e in component.external_references:
        same_object = e.object_identifier == target if e.HasField("object_identifier") else target == target_component
        if e.component_identifier == target_component and same_object and e.is_weak == weak:
            return
    e = component.external_references.add()
    e.component_identifier = target_component
    if target != target_component:
        e.object_identifier = target
    if weak:
        e.is_weak = True
    package.mark_changed(METADATA_ID)


def remove_external_reference(package: Package, component: Any, target: int) -> None:
    """Forget that ``component`` refers to the object ``target``."""
    refs = [e for e in component.external_references if not (e.HasField("object_identifier") and e.object_identifier == target)]
    if len(refs) != len(component.external_references):
        del component.external_references[:]
        for e in refs:
            component.external_references.add().CopyFrom(e)
        package.mark_changed(METADATA_ID)


def place_on_slide(slide: "Slide", root_id: int) -> None:
    """Draw the drawable ``root_id`` in front of everything else."""
    s = slide._slide
    package = slide._package
    s.owned_drawables.add().identifier = root_id
    s.drawables_z_order.add().identifier = root_id
    package.add_object_reference(slide._slide_id, root_id)
    # A table lives in the calculation engine's file; Keynote only loads it if
    # the slide's component says it refers to it.
    add_external_reference(package, package.component(component_id_of(package, slide._slide_id)), root_id)
    slide._package.mark_changed(slide._slide_id)
    slide._touched()


def remove_from_slide(slide: "Slide", root_id: int) -> None:
    s = slide._slide
    package = slide._package
    for field in ("owned_drawables", "drawables_z_order", "infos_using_object_placeholder_geometry"):
        kept = [r.identifier for r in getattr(s, field) if r.identifier != root_id]
        del getattr(s, field)[:]
        for i in kept:
            getattr(s, field).add().identifier = i
    package.remove_object_reference(slide._slide_id, root_id)
    remove_external_reference(package, package.component(component_id_of(package, slide._slide_id)), root_id)
    slide._package.mark_changed(slide._slide_id)
    slide._touched()


def forget_objects(component: Any, ids: set) -> None:
    kept = [e for e in component.object_uuid_map_entries if e.identifier not in ids]
    del component.object_uuid_map_entries[:]
    for e in kept:
        component.object_uuid_map_entries.add().CopyFrom(e)


# --- geometry -----------------------------------------------------------------


class Drawable:
    """Something drawn on a slide. Positions and sizes are in points from the slide's top left."""

    kind = "drawable"

    def __init__(self, slide: "Slide", identifier: int):
        self.slide = slide
        self.identifier = identifier
        self._package = slide._package

    @property
    def _archive(self) -> Any:
        return self._package.get(self.identifier)

    @property
    def _info(self) -> Any:
        """The ``TSD.DrawableArchive`` part, which holds the frame."""
        a = self._archive
        while not a.DESCRIPTOR.full_name == "TSD.DrawableArchive":
            a = a.super
        return a

    def __repr__(self) -> str:
        x, y = self.position
        w, h = self.size
        return f"<{type(self).__name__} {self.kind!r} at ({x:g}, {y:g}) size ({w:g}, {h:g})>"

    @property
    def position(self) -> Tuple[float, float]:
        p = self._info.geometry.position
        return (p.x, p.y)

    @position.setter
    def position(self, value: Tuple[float, float]) -> None:
        g = self._info.geometry
        g.position.x, g.position.y = (float(v) for v in value)
        self._changed()

    @property
    def size(self) -> Tuple[float, float]:
        g = self._info.geometry
        if g.size.width == 0 and g.size.height == 0:
            natural = self._natural_size()
            if natural is not None:
                return natural
        return (g.size.width, g.size.height)

    def _natural_size(self) -> Optional[Tuple[float, float]]:
        """The size of a drawable, such as a text box that grows with its text, that has no size of its own."""
        return None

    @size.setter
    def size(self, value: Tuple[float, float]) -> None:
        width, height = (float(v) for v in value)
        if width <= 0 or height <= 0:
            raise ValueError("width and height must be more than 0")
        g = self._info.geometry
        g.size.width, g.size.height = width, height
        self._resized()
        self._changed()

    def _resized(self) -> None:
        pass

    def _changed(self) -> None:
        self._package.mark_changed(self.identifier)
        self.slide._touched()

    def to_dict(self) -> dict:
        x, y = self.position
        w, h = self.size
        return {"type": self.kind, "x": x, "y": y, "width": w, "height": h}

    def _before_delete(self) -> None:
        pass

    def _owned_elsewhere(self, owned: List[int]) -> List[int]:
        """Objects that belong to this drawable but that nothing in it refers to."""
        return []


# --- shapes -------------------------------------------------------------------

# Shape kinds, and what Keynote calls each one's outline.
SHAPE_KINDS = (
    "rectangle",
    "rounded rectangle",
    "oval",
    "triangle",
    "diamond",
    "pentagon",
    "hexagon",
    "octagon",
    "star",
    "arrow",
    "double arrow",
    "plus",
)

# Keynote draws its triangle and diamond as paths, other polygons from a number of sides.
_POLYGON_SIDES = {"pentagon": 5, "hexagon": 6, "octagon": 8}
_PATHS = {
    "rectangle": [(0, 0), (1, 0), (1, 1), (0, 1)],
    "triangle": [(0.5, 0), (1, 1), (0, 1)],
    "diamond": [(0, 0.5), (0.5, 1), (1, 0.5), (0.5, 0)],
}
_POINT_TYPES = {"arrow": 1, "left arrow": 0, "double arrow": 10, "star": 100, "plus": 200}


def _path_source(kind: str, width: float, height: float) -> Any:
    """A ``TSD.PathSourceArchive`` for a shape of this kind, with Keynote's default proportions."""
    ps = new_archive("TSD.PathSourceArchive")
    ps.horizontalFlip = False
    ps.verticalFlip = False
    if kind in _PATHS or kind == "oval":
        b = ps.bezier_path_source
        b.naturalSize.width, b.naturalSize.height = width, height
        _bezier(b.path, kind, width, height)
    elif kind == "rounded rectangle":
        s = ps.scalar_path_source
        s.type = s.kTSDRoundedRectangle
        s.scalar = min(width, height) * 0.1
        s.naturalSize.width, s.naturalSize.height = width, height
        s.is_curve_continuous = True
    elif kind in _POLYGON_SIDES:
        s = ps.scalar_path_source
        s.type = s.kTSDRegularPolygon
        s.scalar = _POLYGON_SIDES[kind]
        s.naturalSize.width, s.naturalSize.height = width, height
        s.is_curve_continuous = False
    elif kind in _POINT_TYPES:
        p = ps.point_path_source
        p.type = _POINT_TYPES[kind]
        if kind == "star":
            p.point.x, p.point.y = 5, 0.382  # points, inner radius as a fraction of the outer
        elif kind == "plus":
            p.point.x, p.point.y = width / 3, height / 3
        else:
            # Keynote's defaults: the head's length in points, and the shaft's thickness as a fraction of the height.
            head = 64.0 if kind == "arrow" else 44.0
            p.point.x, p.point.y = min(head, width / (2 if kind == "arrow" else 4)), 0.34
        p.naturalSize.width, p.naturalSize.height = width, height
    else:
        raise ValueError(f"shape must be one of {', '.join(SHAPE_KINDS)}, not {kind!r}")
    return ps


def _bezier(path: Any, kind: str, w: float, h: float) -> None:
    def add(element_type: int, *points: Tuple[float, float]) -> None:
        e = path.elements.add()
        e.type = element_type
        for x, y in points:
            pt = e.points.add()
            pt.x, pt.y = x, y

    MOVE, LINE, CURVE, CLOSE = 1, 2, 4, 5
    if kind in _PATHS:
        # Closed, then a move back to the start, as Keynote writes them.
        points = [(x * w, y * h) for x, y in _PATHS[kind]]
        add(MOVE, points[0])
        for pt in points[1:]:
            add(LINE, pt)
        add(CLOSE)
        add(MOVE, points[0])
        return
    # An ellipse as four cubic curves.
    k = 4 * (math.sqrt(2) - 1) / 3
    rx, ry = w / 2, h / 2
    add(MOVE, (w, ry))
    add(CURVE, (w, ry + ry * k), (rx + rx * k, h), (rx, h))
    add(CURVE, (rx - rx * k, h), (0, ry + ry * k), (0, ry))
    add(CURVE, (0, ry - ry * k), (rx - rx * k, 0), (rx, 0))
    add(CURVE, (rx + rx * k, 0), (w, ry - ry * k), (w, ry))
    add(CLOSE)


def _kind_of_path(ps: Any) -> str:
    if ps.HasField("scalar_path_source"):
        s = ps.scalar_path_source
        if s.type == s.kTSDRoundedRectangle:
            return "rounded rectangle"
        if s.type == s.kTSDChevron:
            return "chevron"
        sides = {v: k for k, v in _POLYGON_SIDES.items()}
        sides.update({3: "triangle", 4: "diamond"})
        return sides.get(int(round(s.scalar)), "polygon")
    if ps.HasField("point_path_source"):
        names = {v: k for k, v in _POINT_TYPES.items()}
        return names.get(ps.point_path_source.type, "shape")
    if ps.HasField("bezier_path_source"):
        b = ps.bezier_path_source
        elements = list(b.path.elements)
        types = [e.type for e in elements]
        if types.count(4) == 4 and 2 not in types:
            return "oval"
        if 3 not in types and 4 not in types and types.count(1) <= 2:
            w, h = b.naturalSize.width or 1, b.naturalSize.height or 1
            outline = []
            for e in elements:
                if e.type == 5:
                    break
                outline.extend((round(pt.x / w, 3), round(pt.y / h, 3)) for pt in e.points)
            for name, points in _PATHS.items():
                if _same_polygon(outline, points):
                    return name
        return "custom"
    if ps.HasField("callout_path_source"):
        return "callout"
    return "shape"


def _same_polygon(outline: List[Tuple[float, float]], points: List[Tuple[float, float]]) -> bool:
    """Whether ``outline`` visits the same corners as ``points``, from any start and in either direction."""
    if len(outline) != len(points):
        return False
    n = len(points)
    for start in range(n):
        for step in (1, -1):
            if all(abs(outline[i][0] - points[(start + step * i) % n][0]) < 0.01 and abs(outline[i][1] - points[(start + step * i) % n][1]) < 0.01 for i in range(n)):
                return True
    return False


def _resize_path(ps: Any, width: float, height: float) -> None:
    if ps.HasField("bezier_path_source"):
        b = ps.bezier_path_source
        old_w, old_h = b.naturalSize.width or 1, b.naturalSize.height or 1
        for e in b.path.elements:
            for pt in e.points:
                pt.x, pt.y = pt.x * width / old_w, pt.y * height / old_h
        b.naturalSize.width, b.naturalSize.height = width, height
    else:
        for field in ("scalar_path_source", "point_path_source", "callout_path_source"):
            if ps.HasField(field):
                source = getattr(ps, field)
                size = source.natural_size if field == "callout_path_source" else source.naturalSize
                size.width, size.height = width, height


class Shape(Drawable):
    """A shape or text box. ``kind`` is e.g. ``"rectangle"``, ``"oval"`` or ``"text box"``."""

    @property
    def _shape(self) -> Any:
        return self._archive.super  # TSD.ShapeArchive

    @property
    def is_text_box(self) -> bool:
        return bool(self._archive.is_text_box)

    @property
    def kind(self) -> str:  # type: ignore[override]
        return "text box" if self.is_text_box else _kind_of_path(self._shape.pathsource)

    def _resized(self) -> None:
        width, height = self.size
        _resize_path(self._shape.pathsource, width, height)
        self._info.geometry.flags = 3

    def _natural_size(self) -> Optional[Tuple[float, float]]:
        ps = self._shape.pathsource
        if ps.HasField("bezier_path_source"):
            n = ps.bezier_path_source.naturalSize
            return (n.width, n.height)
        return None

    @property
    def text_storage(self) -> Optional[Text]:
        a = self._archive
        if not a.HasField("owned_storage"):
            return None
        return Text(self._package, a.owned_storage.identifier)

    @property
    def text(self) -> str:
        t = self.text_storage
        return "" if t is None else str(t)

    @text.setter
    def text(self, value: Union[str, Iterable[ParagraphInput]]) -> None:
        t = self.text_storage
        if t is None:
            raise ValueError("this shape has no text")
        t.set_paragraphs(value.split("\n") if isinstance(value, str) else value)
        self.slide._touched()

    def _own_style(self) -> Any:
        """The shape's style, made into a variation of the theme's style first if need be."""
        p = self._package
        style_id = self._shape.style.identifier
        style = p.get(style_id)
        if not style.super.super.is_variation:
            theme_style = style_id
            style_id, style = add_variation_style(p, theme_style)
            self._shape.style.identifier = style_id
            p.remove_object_reference(self.identifier, theme_style)
            p.add_object_reference(self.identifier, style_id)
            add_external_reference(p, p.component_for_file(p.file_of(self.identifier)), style_id)
            self._changed()
        return style_id, style

    def _effective(self, field: str) -> Any:
        """The shape style property ``field``, following the style's parents."""
        p = self._package
        style = p.get(self._shape.style.identifier)
        while True:
            props = style.super.shape_properties
            if props.HasField(field):
                return getattr(props, field)
            if not style.super.super.HasField("parent"):
                return None
            style = p.deref(style.super.super.parent)

    @property
    def fill(self) -> Optional[str]:
        """Fill colour as ``"#rrggbb"``, or ``None`` for no fill, a gradient or an image."""
        fill = self._effective("fill")
        if fill is None or not fill.HasField("color"):
            return None
        return color_hex(fill.color)

    @fill.setter
    def fill(self, value: Optional[Color]) -> None:
        style_id, style = self._own_style()
        props = style.super.shape_properties
        if not props.HasField("fill"):
            style.super.override_count += 1
        props.fill.Clear()
        if value is None:
            props.fill.SetInParent()
        else:
            _set_color(props.fill.color, parse_color(value))
        self._package.mark_changed(style_id)
        self.slide._touched()

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["text"] = self.text
        if not self.is_text_box:
            d["fill"] = self.fill
        return d


def add_shape(
    slide: "Slide",
    kind: str,
    x: float,
    y: float,
    width: float,
    height: float,
    text: Union[None, str, Iterable[ParagraphInput]] = None,
    style: int = 0,
    fill: Optional[Color] = None,
) -> Shape:
    p = slide._package
    is_text_box = kind == "text box"
    if not is_text_box and kind not in SHAPE_KINDS:
        raise ValueError(f"shape must be one of {', '.join(SHAPE_KINDS + ('text box',))}, not {kind!r}")
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be more than 0")
    if not 0 <= style <= 5:
        raise ValueError("style must be 0 to 5, one of the theme's six shape styles")
    if is_text_box and fill is not None:
        raise ValueError("text boxes have no fill")

    style_id = style_named(p, "textbox-0-shapestyle" if is_text_box else f"shape-{style}-shapestyle")
    para_style = p.get(style_id).shape_properties.paragraph_style.identifier
    list_style = style_named(p, "text-0-liststyle-None")
    sheet_id = stylesheet_id(p)

    slide_file = p.file_of(slide._slide_id)
    component = p.component_for_file(slide_file)
    shape_id, caption_id, title_id, storage_id = (p.new_identifier() for _ in range(4))

    storage = new_archive("TSWP.StorageArchive")
    storage.style_sheet.identifier = sheet_id
    storage.text.append("")
    storage.table_para_style.entries.add(character_index=0).object.identifier = para_style
    storage.table_para_data.entries.add(character_index=0, first=0, second=0)
    storage.table_list_style.entries.add(character_index=0).object.identifier = list_style
    storage.in_document = True
    storage.table_para_starts.entries.add(character_index=0, first=0, second=0)
    storage.table_para_bidi.entries.add(character_index=0, first=0, second=0)
    storage.table_drop_cap_style.entries.add(character_index=0)

    info = new_archive("TSWP.ShapeInfoArchive")
    d = info.super.super
    d.geometry.position.x, d.geometry.position.y = float(x), float(y)
    d.geometry.size.width, d.geometry.size.height = float(width), float(height)
    d.geometry.flags = 3
    d.geometry.angle = 0
    d.parent.identifier = slide._slide_id
    wrap = d.exterior_text_wrap
    wrap.type, wrap.direction, wrap.fit_type = 4, 2, 1
    wrap.margin, wrap.alpha_threshold, wrap.is_html_wrap = 12, 0.5, False
    d.locked = False
    d.aspect_ratio_locked = False
    d.title.identifier = title_id
    d.caption.identifier = caption_id
    d.title_hidden = False
    d.caption_hidden = False
    info.super.style.identifier = style_id
    info.super.pathsource.CopyFrom(_path_source("rectangle" if is_text_box else kind, float(width), float(height)))
    info.super.strokePatternOffsetDistance = 0
    info.deprecated_storage.identifier = storage_id
    info.owned_storage.identifier = storage_id
    info.is_text_box = is_text_box

    captions = [new_archive("TSD.StandinCaptionArchive") for _ in range(2)]
    p.add_segment(slide_file, IWAArchiveSegment(make_header(shape_id, SHAPE_INFO, [caption_id, title_id, style_id, storage_id]), [info]))
    p.add_segment(slide_file, IWAArchiveSegment(make_header(caption_id, CAPTION), [captions[0]]))
    p.add_segment(slide_file, IWAArchiveSegment(make_header(title_id, CAPTION), [captions[1]]))
    p.add_segment(slide_file, IWAArchiveSegment(make_header(storage_id, STORAGE, [para_style, list_style]), [storage]))
    for identifier in (shape_id, caption_id, title_id, storage_id):
        _add_uuid(component, identifier)
    for target in (style_id, para_style, list_style):
        add_external_reference(p, component, target)
    p.mark_changed(METADATA_ID)

    place_on_slide(slide, shape_id)
    shape = Shape(slide, shape_id)
    if text is not None:
        shape.text = text
    if fill is not None:
        shape.fill = fill
    return shape


def delete_drawable(slide: "Slide", drawable: Drawable) -> None:
    """Remove a drawable and everything it owns, wherever in the package that is."""
    from .clone import owned_objects, remove_objects

    drawable._before_delete()
    remove_from_slide(slide, drawable.identifier)
    ids = owned_objects(slide._package, drawable.identifier, {slide._slide_id})
    ids += drawable._owned_elsewhere(ids)
    remove_objects(slide._package, ids)


def drawables_of(slide: "Slide") -> List[Drawable]:
    """Every drawable on the slide besides its placeholders, back to front."""
    from .charts import Chart
    from .tables import Table

    out: List[Drawable] = []
    p = slide._package
    for ref in slide._slide.drawables_z_order:
        if ref.identifier not in p:
            continue
        name = type_name_of(p.get(ref.identifier))
        if name == "TSWP.ShapeInfoArchive":
            out.append(Shape(slide, ref.identifier))
        elif name == "TST.TableInfoArchive":
            out.append(Table(slide, ref.identifier))
        elif name == "TSCH.ChartDrawableArchive":
            out.append(Chart(slide, ref.identifier))
    return out
