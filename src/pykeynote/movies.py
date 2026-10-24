"""Video and audio on slides: read, add and remove them.

Keynote keeps both as a ``TSD.MovieArchive``; a sound has ``audioOnly`` set
and no size, and sits in the middle of the slide. Like an image, a movie is
listed in the slide's ``owned_drawables`` and ``drawables_z_order``, and its
file is a data file in ``Data/`` (see :mod:`pykeynote.media`). A video also
has a poster image, the picture shown before it plays.

pykeynote reads the length and picture size from the file itself, so it
takes MPEG-4 and QuickTime files: ``.mp4``, ``.m4v``, ``.mov`` and ``.m4a``.
It can't decode video, so unless you give a ``poster`` the poster is black.

Filling a layout's media placeholder turns the placeholder into a movie,
as Keynote does: it keeps its place and tag, and the video fits inside it.
"""

from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

from keynote_parser.codec import IWAArchiveSegment, import_version

from . import media as _media
from .package import new_uuid_parts

if TYPE_CHECKING:
    from .document import Slide

_MOVIE_TYPE = 3007  # TSD.MovieArchive
_DEFAULT_STYLE = "movie-0-movieStyle"

MediaSource = Union[str, "os.PathLike[str]", bytes]
LOOPS = {"none": 0, "repeat": 1, "back and forth": 2}


@dataclass(frozen=True)
class Movie:
    """A video or sound on a slide.

    ``position`` and ``size`` are in points from the slide's top left; a
    sound has no size. ``duration`` is in seconds and ``volume`` from 0 to 1.
    ``loop`` is ``"none"``, ``"repeat"`` or ``"back and forth"``.
    """

    identifier: int
    position: Tuple[float, float]
    size: Tuple[float, float]
    pixel_size: Tuple[int, int]
    duration: float
    audio_only: bool
    volume: float
    loop: str
    description: str
    placeholder: Optional[str]
    filename: Optional[str]
    name: Optional[str]
    data: Optional[bytes] = field(default=None, repr=False, compare=False)


# --- reading MPEG-4 and QuickTime files -------------------------------------------

_CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"udta"}


def _boxes(data: bytes, start: int, end: int):
    i = start
    while i + 8 <= end:
        size, kind = struct.unpack(">I4s", data[i : i + 8])
        header = 8
        if size == 1:
            size = struct.unpack(">Q", data[i + 8 : i + 16])[0]
            header = 16
        elif size == 0:
            size = end - i
        if size < header or i + size > end:
            break
        yield kind, i + header, i + size
        i += size


def media_info(data: bytes) -> Tuple[str, float, Optional[Tuple[int, int]]]:
    """``(format, seconds, (width, height))`` of an MPEG-4 or QuickTime file; the size is ``None`` for sound."""
    top = list(_boxes(data, 0, len(data)))
    if not top or top[0][0] not in (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip"):
        raise ValueError("unsupported media: pykeynote can add MPEG-4 and QuickTime files (.mp4, .m4v, .mov, .m4a)")
    brand = b""
    if top[0][0] == b"ftyp":
        brand = data[top[0][1] : top[0][1] + 4]
    duration = None
    video: Optional[Tuple[int, int]] = None
    has_sound = False

    def walk(start: int, end: int, track: Dict[str, Any]) -> None:
        nonlocal duration
        for kind, s, e in _boxes(data, start, end):
            if kind == b"mvhd":
                if data[s] == 1:
                    timescale, length = struct.unpack(">IQ", data[s + 20 : s + 32])
                else:
                    timescale, length = struct.unpack(">II", data[s + 12 : s + 20])
                duration = length / timescale if timescale else 0.0
            elif kind == b"tkhd":
                w, h = struct.unpack(">II", data[e - 8 : e])
                track["size"] = (w >> 16, h >> 16)
            elif kind == b"hdlr":
                track["handler"] = data[s + 8 : s + 12]
            elif kind in _CONTAINERS:
                walk(s, e, track)

    for kind, s, e in top:
        if kind != b"moov":
            continue
        for sub, ss, se in _boxes(data, s, e):
            if sub == b"trak":
                track: Dict[str, Any] = {}
                walk(ss, se, track)
                if track.get("handler") == b"vide" and track.get("size", (0, 0)) != (0, 0) and video is None:
                    video = track["size"]
                elif track.get("handler") == b"soun":
                    has_sound = True
            elif sub == b"mvhd":
                walk(s, e, {})
    if duration is None:
        raise ValueError("this file has no movie header, so it isn't a playable MPEG-4 or QuickTime file")
    if video is None and not has_sound:
        raise ValueError("this file has neither video nor sound")
    if video is None:
        fmt = "m4a"
    elif brand == b"qt  ":
        fmt = "mov"
    elif brand.startswith(b"M4V"):
        fmt = "m4v"
    else:
        fmt = "mp4"
    return fmt, duration, video


def _black_png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    rows = (b"\x00" + b"\x00\x00\x00" * width) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, 9))
        + chunk(b"IEND", b"")
    )


# --- reading -------------------------------------------------------------------


def _is_movie(obj: Any) -> bool:
    return getattr(obj, "DESCRIPTOR", None) is not None and obj.DESCRIPTOR.full_name == "TSD.MovieArchive"


def _movie_ids(slide: "Slide") -> List[int]:
    # Live video (a camera feed) is a movie too, but has no file, so it's left out.
    p = slide._package
    out = []
    for ref in slide._slide.drawables_z_order:
        if ref.identifier in p and _is_movie(p.get(ref.identifier)) and not p.get(ref.identifier).is_live_video:
            out.append(ref.identifier)
    return out


def read_movie(slide: "Slide", identifier: int) -> Movie:
    p = slide._package
    obj = p.get(identifier)
    g = obj.super.geometry
    info = _media._data_info(p, obj.movieData.identifier) if obj.HasField("movieData") else None
    path = f"Data/{info.file_name}" if info is not None and info.file_name else None
    data = p.read_file(path) if path and path in p.filenames else None
    loop = {v: k for k, v in LOOPS.items()}.get(obj.loop_option, "none")
    return Movie(
        identifier=identifier,
        position=(g.position.x, g.position.y),
        size=(g.size.width, g.size.height),
        pixel_size=(int(obj.naturalSize.width), int(obj.naturalSize.height)),
        duration=obj.endTime - obj.startTime,
        audio_only=obj.audioOnly,
        volume=obj.volume,
        loop=loop,
        description=obj.super.accessibility_description,
        placeholder=_media._placeholder_tags(slide).get(identifier),
        filename=info.file_name if data is not None else None,
        name=(info.preferred_file_name or info.file_name) if data is not None else None,
        data=data,
    )


def read_movies(slide: "Slide") -> List[Movie]:
    """The slide's videos and sounds, back to front."""
    return [read_movie(slide, i) for i in _movie_ids(slide)]


def _resolve(slide: "Slide", target: Union[Movie, int, str]) -> int:
    ids = _movie_ids(slide)
    if isinstance(target, Movie):
        target = target.identifier
    if isinstance(target, str):
        for identifier, tag in _media._placeholder_tags(slide).items():
            if tag == target and identifier in ids:
                return identifier
        raise ValueError(f"slide {slide.index} has no movie in placeholder {target!r}")
    if isinstance(target, int):
        if target in ids:
            return target
        if -len(ids) <= target < len(ids):
            return ids[target]
    raise ValueError(f"slide {slide.index} has no movie or sound {target!r}")


# --- changing ------------------------------------------------------------------


def _load(source: MediaSource, name: Optional[str]) -> Tuple[bytes, str]:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source), name or "movie"
    path = os.fspath(source)
    if "://" in path:
        raise ValueError(f"can't add {path!r}: download the file and add that instead")
    with open(path, "rb") as fh:
        return fh.read(), name or os.path.basename(path)


def _movie_style(package: Any) -> int:
    for identifier, obj in package.objects("TSD.MediaStyleArchive"):
        if obj.super.name == "" and obj.super.style_identifier == _DEFAULT_STYLE:
            return identifier
    return _media._default_style(package)


def add_movie(
    slide: "Slide",
    source: MediaSource,
    position: Optional[Tuple[float, float]] = None,
    size: Optional[Tuple[Optional[float], Optional[float]]] = None,
    description: Optional[str] = None,
    placeholder: Union[None, bool, str] = None,
    poster: Optional[_media.ImageSource] = None,
    loop: str = "none",
    volume: float = 1.0,
    name: Optional[str] = None,
) -> Movie:
    data, name = _load(source, name)
    fmt, duration, video = media_info(data)
    if loop not in LOOPS:
        raise ValueError(f"loop must be one of {', '.join(LOOPS)}, not {loop!r}")
    if not 0 <= volume <= 1:
        raise ValueError("volume goes from 0 to 1")
    p = slide._package
    s = slide._slide
    slide_file = p.file_of(slide._slide_id)
    component = p.component_for_file(slide_file)
    slide_w, slide_h = slide.presentation.size

    if placeholder is None and video is not None and position is None and size is None:
        free = [i for i in _media.placeholders(slide) if i.is_sample]
        placeholder = free[0].placeholder if free else False
    if placeholder and video is None:
        raise ValueError("a sound can't fill a media placeholder")
    if placeholder is True:
        free = [i for i in _media.placeholders(slide) if i.is_sample]
        if not free:
            raise ValueError(f"slide {slide.index} has no empty media placeholder")
        placeholder = free[0].placeholder

    classes = import_version()[1]
    movie = classes["TSD.MovieArchive"]()
    if placeholder:
        movie_id = _media._resolve(slide, placeholder)
        image = p.get(movie_id)
        (vx, vy), (vw, vh) = _media._frame(p, image)
        width, height = _media._fit(video, (vw, vh), cover=False)
        x, y = vx + (vw - width) / 2, vy + (vh - height) / 2
        movie.super.CopyFrom(image.super)
        style_id = image.style.identifier
        movie.flags = 3
        segment = p.segment(movie_id)
        old_data = list(segment.header.message_infos[0].data_references)
        gone = []
        if image.HasField("mask") and image.mask.identifier in p:
            gone.append(image.mask.identifier)
        _media._drop_data(p, component, movie_id, old_data)
        info = segment.header.message_infos[0]
        refs = [r for r in info.object_references if r not in gone]
        del info.object_references[:]
        info.object_references.extend(refs)
        info.type = _MOVIE_TYPE
        segment.objects[0] = movie
        for identifier in gone:
            p.remove_segment(identifier)
        kept = [e for e in component.object_uuid_map_entries if e.identifier not in gone]
        del component.object_uuid_map_entries[:]
        for e in kept:
            component.object_uuid_map_entries.add().CopyFrom(e)
    else:
        if video is None:
            # Keynote puts a sound in the middle of the slide, with no size.
            width = height = 0.0
            if position is None:
                position = (slide_w / 2, slide_h / 2)
        else:
            width, height = _media._size_for(slide, video, size)
            if position is None:
                position = ((slide_w - width) / 2, (slide_h - height) / 2)
        x, y = float(position[0]), float(position[1])
        movie_id = p.new_identifier()
        style_id = _movie_style(p)
        d = movie.super
        d.geometry.flags = 3
        d.geometry.angle = 0.0
        d.parent.identifier = slide._slide_id
        wrap = d.exterior_text_wrap
        wrap.type, wrap.direction, wrap.fit_type = 4, 2, 1
        wrap.margin, wrap.alpha_threshold, wrap.is_html_wrap = 12.0, 0.5, False
        d.locked = False
        d.aspect_ratio_locked = True
        movie.flags = 0
        header = _media._header(movie_id, _MOVIE_TYPE)
        header.message_infos[0].object_references.append(style_id)
        p.add_segment(slide_file, IWAArchiveSegment(header, [movie]))
        entry = component.object_uuid_map_entries.add()
        entry.identifier = movie_id
        entry.uuid.lower, entry.uuid.upper = new_uuid_parts()
        _media._refer_to_external(p, component, style_id)
        s.owned_drawables.add().identifier = movie_id
        s.drawables_z_order.add().identifier = movie_id
        p.add_object_reference(slide._slide_id, movie_id)

    g = movie.super.geometry
    g.position.x, g.position.y = x, y
    g.size.width, g.size.height = width, height
    movie.super.accessibility_description = description or ""
    movie.startTime = 0.0
    movie.endTime = duration
    movie.posterTime = 0.0
    movie.volume = float(volume)
    movie.audioOnly = video is None
    movie.streaming = False
    movie.loop_option = LOOPS[loop]
    movie.style.identifier = style_id
    movie.originalSize.width, movie.originalSize.height = width, height
    movie.naturalSize.width, movie.naturalSize.height = video or (0, 0)

    data_id = _media.add_data(p, data, name, fmt, None)
    movie.movieData.identifier = data_id
    _media._use_data(p, component, movie_id, data_id)
    if video is not None:
        if poster is None:
            poster_data, poster_name, poster_fmt, poster_size = _black_png(*video), "posterImage.png", "png", video
        else:
            poster_data, poster_name = _media._load(poster, None)
            poster_fmt, pw, ph = _media.image_format(poster_data)
            poster_size = (pw, ph)
        poster_id = _media.add_data(p, poster_data, poster_name, poster_fmt, poster_size)
        movie.posterImageData.identifier = poster_id
        _media._use_data(p, component, movie_id, poster_id)
    p.mark_changed(movie_id)
    p.mark_changed(slide._slide_id)
    slide._touched()
    return read_movie(slide, movie_id)


def remove_movie(slide: "Slide", target: Union[Movie, int, str]) -> None:
    _media.remove_drawable_media(slide, _resolve(slide, target))
