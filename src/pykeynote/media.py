"""Images on slides: read, add, replace and remove them.

An image is a ``TSD.ImageArchive`` in the slide's component file, listed in
``KN.SlideArchive.owned_drawables`` and ``drawables_z_order``. Its pixels are
a data file in ``Data/``: the image points at it with a ``TSP.DataReference``,
``TSP.PackageMetadata.datas`` holds a ``TSP.DataInfo`` for it (file name,
SHA-1 digest, length), and both the image's archive header and the slide's
component list which data each object uses.

A layout's media placeholder is an image tagged ``"Media"`` (or
``"Media-1"`` and so on) in ``KN.SlideArchive.sage_tag_to_info_map``. Until
it is replaced, it shows one of the theme's sample photos, which isn't stored
in the file: its ``DataInfo`` has a ``document_resource_locator`` instead of a
file name. A placeholder crops its photo with a ``TSD.MaskArchive``, a child
of the image whose geometry is relative to the image. Filling one keeps the
mask where it is and scales the new picture to cover it.
"""

from __future__ import annotations

import hashlib
import os
import re
import struct
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, List, Optional, Tuple, Union

from keynote_parser.codec import IWAArchiveSegment, import_version

from .package import METADATA_ID, Package, new_uuid_parts

if TYPE_CHECKING:
    from .document import Slide

_IMAGE_TYPE = 3005  # TSD.ImageArchive
_MESSAGE_VERSION = (1, 0, 5)
_DEFAULT_STYLE = "image-0-imageStyle"

ImageSource = Union[str, "os.PathLike[str]", bytes]


@dataclass(frozen=True)
class Image:
    """One image on a slide.

    ``position`` and ``size`` are the part you see, in points from the
    slide's top left, so for a cropped photo they are the crop, not the
    whole picture. ``data`` is ``None`` for a placeholder still showing the
    theme's sample photo, which Keynote keeps outside the file.
    """

    identifier: int
    position: Tuple[float, float]
    size: Tuple[float, float]
    pixel_size: Tuple[int, int]
    description: str  # accessibility description, Markdown's alt text
    placeholder: Optional[str]  # the layout's tag, e.g. "Media", if this is a media placeholder
    filename: Optional[str]  # the file's name in Data/
    name: Optional[str]  # the name it was added under, e.g. "robot.png"
    data: Optional[bytes] = field(default=None, repr=False, compare=False)

    @property
    def is_sample(self) -> bool:
        """True for a media placeholder that still shows the theme's sample photo."""
        return self.data is None


# --- image files ---------------------------------------------------------------

_EXTENSIONS = {"png": "png", "jpeg": "jpeg", "gif": "gif"}


def image_format(data: bytes) -> Tuple[str, int, int]:
    """``(format, width, height)`` of PNG, JPEG or GIF data, read from its header."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        width, height = struct.unpack(">II", data[16:24])
        return "png", width, height
    if data[:6] in (b"GIF87a", b"GIF89a"):
        width, height = struct.unpack("<HH", data[6:10])
        return "gif", width, height
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
                i += 1 if marker == 0xFF else 2
                continue
            length = struct.unpack(">H", data[i + 2 : i + 4])[0]
            # Start-of-frame markers, apart from DHT (C4), JPG (C8) and DAC (CC).
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack(">HH", data[i + 5 : i + 9])
                return "jpeg", width, height
            i += 2 + length
    raise ValueError("unsupported image: pykeynote can add PNG, JPEG and GIF files")


def _load(source: ImageSource, name: Optional[str]) -> Tuple[bytes, str]:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source), name or "image"
    path = os.fspath(source)
    if re.match(r"^[a-z]+://", path):
        raise ValueError(f"can't add {path!r}: download the image and add the file instead")
    with open(path, "rb") as fh:
        return fh.read(), name or os.path.basename(path)


def _file_names(name: str, fmt: str, data_id: int) -> Tuple[str, str]:
    stem = os.path.splitext(os.path.basename(name))[0] or "image"
    stem = re.sub(r"[^\w.-]+", "-", stem).strip("-") or "image"
    ext = _EXTENSIONS[fmt]
    return f"{stem}.{ext}", f"{stem}-{data_id}.{ext}"


def add_data(package: Package, data: bytes, name: str, fmt: str, pixel_size: Tuple[int, int]) -> int:
    """Store ``data`` in ``Data/`` and return its data identifier. The same bytes are stored once."""
    digest = hashlib.sha1(data).digest()
    meta = package.metadata
    for info in meta.datas:
        if info.digest == digest and info.file_name and f"Data/{info.file_name}" in package.filenames:
            return info.identifier
    data_id = package.new_identifier()
    preferred, file_name = _file_names(name, fmt, data_id)
    info = meta.datas.add()
    info.identifier = data_id
    info.digest = digest
    info.preferred_file_name = preferred
    info.file_name = file_name
    info.materialized_length = len(data)
    attrs = info.attributes.Extensions[_image_data_attributes()]
    attrs.pixel_size.width, attrs.pixel_size.height = pixel_size
    attrs.should_be_interpreted_as_generic_if_untagged = False
    package.write_file(f"Data/{file_name}", data)
    package.mark_changed(METADATA_ID)
    return data_id


def _image_data_attributes() -> Any:
    from keynote_parser.versions.v14_5.generated import TSDArchives_pb2

    return TSDArchives_pb2.ImageDataAttributes.image_data_attributes


def _data_info(package: Package, data_id: int) -> Optional[Any]:
    for info in package.metadata.datas:
        if info.identifier == data_id:
            return info
    return None


def _use_data(package: Package, component: Any, object_id: int, data_id: int) -> None:
    refs = package.segment(object_id).header.message_infos[0].data_references
    if data_id not in refs:
        refs.append(data_id)
    for ref in component.data_references:
        if ref.data_identifier == data_id:
            for o in ref.object_reference_list:
                if o.object_identifier == object_id:
                    return
            added = ref.object_reference_list.add()
            added.object_identifier, added.count = object_id, 1
            break
    else:
        ref = component.data_references.add()
        ref.data_identifier = data_id
        added = ref.object_reference_list.add()
        added.object_identifier, added.count = object_id, 1
    package.mark_changed(object_id)
    package.mark_changed(METADATA_ID)


def _drop_data(package: Package, component: Any, object_id: int, data_ids: List[int]) -> None:
    """Stop ``object_id`` using these data, and delete any data nothing uses any more."""
    header_refs = package.segment(object_id).header.message_infos[0].data_references if object_id in package else None
    if header_refs is not None:
        kept = [d for d in header_refs if d not in data_ids]
        del header_refs[:]
        header_refs.extend(kept)
        package.mark_changed(object_id)
    for ref in list(component.data_references):
        if ref.data_identifier not in data_ids:
            continue
        kept_objects = [o for o in ref.object_reference_list if o.object_identifier != object_id]
        del ref.object_reference_list[:]
        for o in kept_objects:
            ref.object_reference_list.add().CopyFrom(o)
    kept_refs = [r for r in component.data_references if len(r.object_reference_list) > 0]
    del component.data_references[:]
    for r in kept_refs:
        component.data_references.add().CopyFrom(r)
    meta = package.metadata
    in_use = {r.data_identifier for c in meta.components for r in c.data_references}
    described = set()
    if meta.HasField("data_metadata_map") and meta.data_metadata_map.identifier in package:
        described = {e.data_identifier for e in package.deref(meta.data_metadata_map).data_metadata_entries}
    for data_id in data_ids:
        info = _data_info(package, data_id)
        # Only delete files pykeynote could have added; theme resources stay.
        if data_id in in_use or info is None or not info.file_name or data_id in described:
            continue
        package.remove_file(f"Data/{info.file_name}")
        kept_infos = [i for i in meta.datas if i.identifier != data_id]
        del meta.datas[:]
        for i in kept_infos:
            meta.datas.add().CopyFrom(i)
    package.mark_changed(METADATA_ID)


# --- reading -------------------------------------------------------------------


def _placeholder_tags(slide: "Slide") -> dict:
    return {e.info.identifier: e.tag for e in slide._slide.sage_tag_to_info_map if e.tag.startswith("Media")}


def _frame(package: Package, image: Any) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    g = image.super.geometry
    if image.HasField("mask") and image.mask.identifier in package:
        m = package.deref(image.mask).super.geometry
        return (g.position.x + m.position.x, g.position.y + m.position.y), (m.size.width, m.size.height)
    return (g.position.x, g.position.y), (g.size.width, g.size.height)


def _image_ids(slide: "Slide") -> List[int]:
    p = slide._package
    out = []
    for ref in slide._slide.drawables_z_order:
        if ref.identifier in p and _is_image(p.get(ref.identifier)):
            out.append(ref.identifier)
    return out


def _is_image(obj: Any) -> bool:
    return getattr(obj, "DESCRIPTOR", None) is not None and obj.DESCRIPTOR.full_name == "TSD.ImageArchive"


def read_image(slide: "Slide", identifier: int) -> Image:
    p = slide._package
    obj = p.get(identifier)
    position, size = _frame(p, obj)
    info = _data_info(p, obj.data.identifier) if obj.HasField("data") else None
    name = f"Data/{info.file_name}" if info is not None and info.file_name else None
    data = p.read_file(name) if name and name in p.filenames else None
    return Image(
        identifier=identifier,
        position=position,
        size=size,
        pixel_size=(int(obj.naturalSize.width), int(obj.naturalSize.height)),
        description=obj.super.accessibility_description,
        placeholder=_placeholder_tags(slide).get(identifier),
        filename=info.file_name if data is not None else None,
        name=(info.preferred_file_name or info.file_name) if data is not None else None,
        data=data,
    )


def read_images(slide: "Slide") -> List[Image]:
    """The slide's images, back to front."""
    return [read_image(slide, i) for i in _image_ids(slide)]


def placeholders(slide: "Slide") -> List[Image]:
    """The slide's media placeholders in reading order, left to right and top to bottom."""
    rows: List[List[Image]] = []
    for image in sorted((i for i in read_images(slide) if i.placeholder is not None), key=lambda i: i.position[1]):
        # Tops within 20 points of each other count as one row.
        if rows and image.position[1] - rows[-1][0].position[1] <= 20:
            rows[-1].append(image)
        else:
            rows.append([image])
    return [image for row in rows for image in sorted(row, key=lambda i: i.position[0])]


# --- changing ------------------------------------------------------------------

Target = Union[Image, int, str]


def _resolve(slide: "Slide", target: Target) -> int:
    ids = _image_ids(slide)
    if isinstance(target, Image):
        target = target.identifier
    if isinstance(target, str):
        for identifier, tag in _placeholder_tags(slide).items():
            if tag == target and identifier in ids:
                return identifier
        raise ValueError(f"slide {slide.index} has no media placeholder {target!r}")
    if isinstance(target, int):
        if target in ids:
            return target
        if -len(ids) <= target < len(ids):
            return ids[target]
    raise ValueError(f"slide {slide.index} has no image {target!r}")


def _header(identifier: int, message_type: int) -> Any:
    archive_info = import_version()[2]
    header = archive_info()
    header.identifier = identifier
    info = header.message_infos.add()
    info.type = message_type
    info.version.extend(_MESSAGE_VERSION)
    info.length = 0  # set when the file is encoded
    return header


def _default_style(package: Package) -> int:
    for identifier, obj in package.objects("TSD.MediaStyleArchive"):
        if obj.super.name == "" and obj.super.style_identifier == _DEFAULT_STYLE:
            return identifier
    for identifier, obj in package.objects("TSD.ImageArchive"):
        if obj.HasField("style"):
            return obj.style.identifier
    raise ValueError("this presentation's theme has no image style to use")


def _refer_to_external(package: Package, component: Any, target: int) -> None:
    """Record that ``component`` refers to ``target``, an object in another component."""
    other = package.component_for_file(package.file_of(target))
    if other.identifier == component.identifier:
        return
    for e in component.external_references:
        if e.component_identifier == other.identifier and e.object_identifier == target:
            return
    e = component.external_references.add()
    e.component_identifier = other.identifier
    e.object_identifier = target
    package.mark_changed(METADATA_ID)


def _fit(pixel_size: Tuple[int, int], box: Tuple[float, float], cover: bool) -> Tuple[float, float]:
    w, h = pixel_size
    scale = (max if cover else min)(box[0] / w, box[1] / h)
    return w * scale, h * scale


def _size_for(slide: "Slide", pixel_size: Tuple[int, int], size: Optional[Tuple[Optional[float], Optional[float]]]):
    w, h = pixel_size
    if size is not None and size[0] is not None and size[1] is not None:
        return float(size[0]), float(size[1])
    if size is not None and size[0] is not None:
        return float(size[0]), size[0] * h / w
    if size is not None and size[1] is not None:
        return size[1] * w / h, float(size[1])
    slide_w, slide_h = slide.presentation.size
    if w <= slide_w * 0.8 and h <= slide_h * 0.8:
        return float(w), float(h)
    return _fit(pixel_size, (slide_w * 0.8, slide_h * 0.8), cover=False)


def add_image(
    slide: "Slide",
    source: ImageSource,
    position: Optional[Tuple[float, float]] = None,
    size: Optional[Tuple[Optional[float], Optional[float]]] = None,
    description: Optional[str] = None,
    placeholder: Union[None, bool, str] = None,
    name: Optional[str] = None,
) -> Image:
    data, name = _load(source, name)
    fmt, w, h = image_format(data)
    if placeholder is None and position is None and size is None:
        # Fill the first media placeholder still showing the theme's sample.
        free = [i for i in placeholders(slide) if i.is_sample]
        placeholder = free[0].placeholder if free else False
    if placeholder:
        if placeholder is True:
            free = [i for i in placeholders(slide) if i.is_sample]
            if not free:
                raise ValueError(f"slide {slide.index} has no empty media placeholder")
            placeholder = free[0].placeholder
        return _replace(slide, _resolve(slide, placeholder), data, name, fmt, (w, h), description)

    p = slide._package
    s = slide._slide
    slide_file = p.file_of(slide._slide_id)
    component = p.component_for_file(slide_file)
    width, height = _size_for(slide, (w, h), size)
    if position is None:
        slide_w, slide_h = slide.presentation.size
        position = ((slide_w - width) / 2, (slide_h - height) / 2)
    style_id = _default_style(p)
    data_id = add_data(p, data, name, fmt, (w, h))

    classes = import_version()[1]
    image_id = p.new_identifier()
    image = classes["TSD.ImageArchive"]()
    d = image.super
    d.geometry.position.x, d.geometry.position.y = float(position[0]), float(position[1])
    d.geometry.size.width, d.geometry.size.height = width, height
    d.geometry.flags = 3
    d.geometry.angle = 0.0
    d.parent.identifier = slide._slide_id
    wrap = d.exterior_text_wrap
    wrap.type, wrap.direction, wrap.fit_type = 4, 2, 1
    wrap.margin, wrap.alpha_threshold, wrap.is_html_wrap = 12.0, 0.5, False
    d.locked = False
    d.aspect_ratio_locked = True
    d.accessibility_description = description or ""
    image.style.identifier = style_id
    image.originalSize.width, image.originalSize.height = width, height
    image.flags = 1
    image.naturalSize.width, image.naturalSize.height = w, h
    image.data.identifier = data_id
    image.interpretsUntaggedImageDataAsGeneric = False
    header = _header(image_id, _IMAGE_TYPE)
    header.message_infos[0].object_references.append(style_id)
    p.add_segment(slide_file, IWAArchiveSegment(header, [image]))
    entry = component.object_uuid_map_entries.add()
    entry.identifier = image_id
    entry.uuid.lower, entry.uuid.upper = new_uuid_parts()
    _use_data(p, component, image_id, data_id)
    _refer_to_external(p, component, style_id)

    s.owned_drawables.add().identifier = image_id
    s.drawables_z_order.add().identifier = image_id
    p.add_object_reference(slide._slide_id, image_id)
    p.mark_changed(slide._slide_id)
    slide._touched()
    return read_image(slide, image_id)


def replace_image(
    slide: "Slide", target: Target, source: ImageSource, description: Optional[str] = None, name: Optional[str] = None
) -> Image:
    data, name = _load(source, name)
    fmt, w, h = image_format(data)
    return _replace(slide, _resolve(slide, target), data, name, fmt, (w, h), description)


def _replace(
    slide: "Slide",
    image_id: int,
    data: bytes,
    name: str,
    fmt: str,
    pixel_size: Tuple[int, int],
    description: Optional[str],
) -> Image:
    p = slide._package
    component = p.component_for_file(p.file_of(slide._slide_id))
    image = p.get(image_id)
    (vx, vy), (vw, vh) = _frame(p, image)
    old_data = [d for d in p.segment(image_id).header.message_infos[0].data_references]
    if image.HasField("mask") and image.mask.identifier in p:
        # Cover the crop, centred, and move the mask so the crop stays put.
        width, height = _fit(pixel_size, (vw, vh), cover=True)
        x, y = vx + (vw - width) / 2, vy + (vh - height) / 2
        mask = p.deref(image.mask)
        mask.super.geometry.position.x, mask.super.geometry.position.y = vx - x, vy - y
        p.mark_changed(image.mask.identifier)
    else:
        width, height = _fit(pixel_size, (vw, vh), cover=False)
        x, y = vx + (vw - width) / 2, vy + (vh - height) / 2
    g = image.super.geometry
    g.position.x, g.position.y = x, y
    g.size.width, g.size.height = width, height
    image.originalSize.width, image.originalSize.height = width, height
    image.naturalSize.width, image.naturalSize.height = pixel_size
    for f in (
        "thumbnailData",
        "originalData",
        "originalSVGData",
        "instantAlphaPath",
        "imageAdjustments",
        "enhancedImageData",
        "adjustedImageData",
        "thumbnailAdjustedImageData",
        "traced_path",
        "attribution",
        "background_removed",
    ):
        image.ClearField(f)
    # The old description was of the old picture, as with the theme's sample photos.
    image.super.accessibility_description = description or ""
    data_id = add_data(p, data, name, fmt, pixel_size)
    image.data.identifier = data_id
    _drop_data(p, component, image_id, [d for d in old_data if d != data_id])
    _use_data(p, component, image_id, data_id)
    p.mark_changed(image_id)
    slide._touched()
    return read_image(slide, image_id)


def remove_image(slide: "Slide", target: Target) -> None:
    from . import builds as _builds

    p = slide._package
    s = slide._slide
    image_id = _resolve(slide, target)
    image = p.get(image_id)
    component = p.component_for_file(p.file_of(slide._slide_id))
    _builds.remove_builds_for(slide, image_id)

    data_ids = list(p.segment(image_id).header.message_infos[0].data_references)
    _drop_data(p, component, image_id, data_ids)
    gone = {image_id}
    if image.HasField("mask") and image.mask.identifier in p:
        gone.add(image.mask.identifier)
    for f in ("title", "caption"):
        if image.super.HasField(f) and getattr(image.super, f).identifier in p:
            gone.add(getattr(image.super, f).identifier)
    for identifier in gone:
        if p.file_of(identifier) == p.file_of(slide._slide_id):
            p.remove_segment(identifier)
    for field_name in ("owned_drawables", "drawables_z_order"):
        kept = [r.identifier for r in getattr(s, field_name) if r.identifier != image_id]
        del getattr(s, field_name)[:]
        for identifier in kept:
            getattr(s, field_name).add().identifier = identifier
    kept_tags = [(e.tag, e.info.identifier) for e in s.sage_tag_to_info_map if e.info.identifier != image_id]
    if len(kept_tags) != len(s.sage_tag_to_info_map):
        del s.sage_tag_to_info_map[:]
        for tag, identifier in kept_tags:
            e = s.sage_tag_to_info_map.add()
            e.tag = tag
            e.info.identifier = identifier
    p.remove_object_reference(slide._slide_id, image_id)
    kept = [e for e in component.object_uuid_map_entries if e.identifier not in gone]
    del component.object_uuid_map_entries[:]
    for e in kept:
        component.object_uuid_map_entries.add().CopyFrom(e)
    p.mark_changed(slide._slide_id)
    p.mark_changed(METADATA_ID)
    slide._touched()
