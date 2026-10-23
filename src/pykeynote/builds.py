"""Build animations: how a slide's title, body or shapes appear on click.

A slide lists its builds in ``KN.SlideArchive.builds``, one
``KN.BuildArchive`` per animated object. The order they play in is
``KN.SlideArchive.buildChunks``: one ``KN.BuildChunkArchive`` per click
("event"), so a body built by paragraph has a chunk per paragraph. Chunks
name their build by a UUID, which is also recorded as the build's identity
in the slide's component.

The field values written here are the ones Keynote 14.5 writes for a
default Dissolve or Move In build.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, List, Optional, Union

from keynote_parser.codec import IWAArchiveSegment, import_version

from .package import METADATA_ID, new_uuid_parts

if TYPE_CHECKING:
    from .document import Slide

_BUILD_TYPE = 8  # KN.BuildArchive
_CHUNK_TYPE = 153  # KN.BuildChunkArchive
_MESSAGE_VERSION = (1, 0, 5)
_STALE_CACHE = 0xFFFFFFFF  # tells Keynote to recount builds when it opens the file

_DELIVERY_NAMES = {
    "all at once": "All at Once",
    "by paragraph": "By Paragraph",
    "by bullet": "By Paragraph",
}
_KINDS = {"in": "In", "out": "Out"}

Target = Union[str, int]


@dataclass(frozen=True)
class Build:
    """One build on a slide."""

    target: Union[str, int]  # "title", "body", or the identifier of another drawable
    kind: str  # "in" or "out"
    effect: str  # e.g. "dissolve", "move in"
    delivery: str  # Keynote's delivery name, e.g. "All at Once", "By Paragraph"
    duration: float
    steps: int  # clicks this build takes
    effect_id: str  # Keynote's own effect id, e.g. "apple:dissolve character"


def _effect_id(name: str) -> str:
    if ":" in name:
        return name
    return "apple:" + name.strip().lower().replace("_", " ").replace("-", " ") + " character"


def _effect_name(effect_id: str) -> str:
    name = effect_id.split(":", 1)[-1]
    return name[: -len(" character")] if name.endswith(" character") else name


def _target_name(slide: "Slide", drawable_id: int) -> Union[str, int]:
    s = slide._slide
    if s.HasField("titlePlaceholder") and s.titlePlaceholder.identifier == drawable_id:
        return "title"
    if s.HasField("bodyPlaceholder") and s.bodyPlaceholder.identifier == drawable_id:
        return "body"
    return drawable_id


def read_builds(slide: "Slide") -> List[Build]:
    p = slide._package
    # Play order is the order of the chunks. Keynote doesn't keep
    # ``builds`` in that order when it saves, so sort by each build's first chunk.
    steps: dict = {}
    for ref in slide._slide.buildChunks:
        build_id = p.deref(ref).build.identifier
        steps[build_id] = steps.get(build_id, 0) + 1
    first = {build_id: i for i, build_id in enumerate(steps)}
    refs = sorted(slide._slide.builds, key=lambda r: first.get(r.identifier, len(first)))
    out = []
    for ref in refs:
        b = p.deref(ref)
        a = b.attributes.animationAttributes
        out.append(
            Build(
                target=_target_name(slide, b.drawable.identifier),
                kind=a.animation_type.lower(),
                effect=_effect_name(a.effect),
                delivery=b.delivery,
                duration=a.duration,
                steps=steps.get(ref.identifier, 0),
                effect_id=a.effect,
            )
        )
    return out


def _resolve_target(slide: "Slide", target: Target) -> int:
    s = slide._slide
    shown = {r.identifier for r in s.drawables_z_order}
    if target in ("title", "body"):
        field = "titlePlaceholder" if target == "title" else "bodyPlaceholder"
        if not s.HasField(field) or getattr(s, field).identifier not in shown:
            raise ValueError(f"the {slide.layout!r} layout doesn't show a {target} on slide {slide.index}")
        return getattr(s, field).identifier
    if isinstance(target, int) and target in shown:
        return target
    raise ValueError(f"build target must be 'title', 'body' or a drawable on the slide, not {target!r}")


def _header(identifier: int, message_type: int) -> Any:
    archive_info = import_version()[2]
    header = archive_info()
    header.identifier = identifier
    info = header.message_infos.add()
    info.type = message_type
    info.version.extend(_MESSAGE_VERSION)
    info.length = 0  # set when the file is encoded
    return header


def add_build(
    slide: "Slide",
    target: Target = "body",
    effect: str = "dissolve",
    delivery: Optional[str] = None,
    duration: float = 1.0,
    kind: str = "in",
) -> Build:
    p = slide._package
    s = slide._slide
    drawable_id = _resolve_target(slide, target)
    if kind not in _KINDS:
        raise ValueError(f"kind must be 'in' or 'out', not {kind!r}")
    is_body = target == "body"
    if delivery is None:
        delivery = "by paragraph" if is_body and len(slide.paragraphs) > 1 else "all at once"
    if delivery.lower() not in _DELIVERY_NAMES:
        raise ValueError(f"delivery must be one of {', '.join(sorted(_DELIVERY_NAMES))}, not {delivery!r}")
    delivery_name = _DELIVERY_NAMES[delivery.lower()]
    steps = 1
    if delivery_name == "By Paragraph":
        if target not in ("title", "body"):
            raise ValueError("only text placeholders can be built by paragraph")
        text = slide.body_text if is_body else slide.title_text
        steps = max(1, len([para for para in text.paragraphs if para.text.strip()]))

    classes = import_version()[1]
    slide_file = p.file_of(slide._slide_id)
    component = p.component_for_file(slide_file)
    lower, upper = new_uuid_parts()

    build_id = p.new_identifier()
    build = classes["KN.BuildArchive"]()
    build.drawable.identifier = drawable_id
    build.delivery = delivery_name
    build.duration = 0.0
    build.chunk_id_seed = steps
    attrs = build.attributes
    attrs.eventTrigger = 1
    attrs.ChartRotation3D = 60.0
    a = attrs.animationAttributes
    a.animation_type = _KINDS[kind]
    a.effect = _effect_id(effect)
    a.duration = float(duration)
    a.delay = 0.0
    a.random_number_seed = random.randrange(1, 2**31)
    a.writing_direction_is_rtl = False
    attrs.custom_textDelivery = attrs.kTextDeliveryByObject
    attrs.custom_deliveryOption = attrs.kDeliveryOptionForward
    if a.effect == "apple:move in character":
        # Keynote's defaults for Move In.
        attrs.custom_bounce = True
        attrs.custom_deliveryOption = attrs.kDeliveryOptionBackward
    p.add_segment(slide_file, IWAArchiveSegment(_header(build_id, _BUILD_TYPE), [build]))
    entry = component.object_uuid_map_entries.add()
    entry.identifier = build_id
    entry.uuid.lower, entry.uuid.upper = lower, upper

    s.builds.add().identifier = build_id
    p.add_object_reference(slide._slide_id, build_id)
    for step in range(1, steps + 1):
        chunk_id = p.new_identifier()
        chunk = classes["KN.BuildChunkArchive"]()
        chunk.build.identifier = build_id
        chunk.delay = 0.0
        chunk.duration = float(duration)
        chunk.automatic = False
        chunk.referent = True
        chunk.build_chunk_identifier.build_id.lower = lower
        chunk.build_chunk_identifier.build_id.upper = upper
        chunk.build_chunk_identifier.build_chunk_id = step
        chunk.build_id.lower, chunk.build_id.upper = lower, upper
        p.add_segment(slide_file, IWAArchiveSegment(_header(chunk_id, _CHUNK_TYPE), [chunk]))
        s.buildChunks.add().identifier = chunk_id
        p.add_object_reference(slide._slide_id, chunk_id)

    _builds_changed(slide)
    return read_builds(slide)[-1]


def clear_builds(slide: "Slide") -> None:
    p = slide._package
    s = slide._slide
    gone = {r.identifier for r in s.builds} | {r.identifier for r in s.buildChunks}
    if not gone:
        return
    for identifier in gone:
        p.remove_segment(identifier)
        p.remove_object_reference(slide._slide_id, identifier)
    del s.builds[:]
    del s.buildChunks[:]
    component = p.component_for_file(p.file_of(slide._slide_id))
    kept = [e for e in component.object_uuid_map_entries if e.identifier not in gone]
    del component.object_uuid_map_entries[:]
    for e in kept:
        component.object_uuid_map_entries.add().CopyFrom(e)
    _builds_changed(slide)


def remove_builds_for(slide: "Slide", drawable_id: int) -> None:
    """Remove the builds that animate one drawable, for when it is deleted."""
    p = slide._package
    s = slide._slide
    builds = {r.identifier for r in s.builds if p.deref(r).drawable.identifier == drawable_id}
    if not builds:
        return
    chunks = {r.identifier for r in s.buildChunks if p.deref(r).build.identifier in builds}
    gone = builds | chunks
    for identifier in gone:
        p.remove_segment(identifier)
        p.remove_object_reference(slide._slide_id, identifier)
    for field in ("builds", "buildChunks"):
        kept = [r.identifier for r in getattr(s, field) if r.identifier not in gone]
        del getattr(s, field)[:]
        for identifier in kept:
            getattr(s, field).add().identifier = identifier
    component = p.component_for_file(p.file_of(slide._slide_id))
    kept_entries = [e for e in component.object_uuid_map_entries if e.identifier not in gone]
    del component.object_uuid_map_entries[:]
    for e in kept_entries:
        component.object_uuid_map_entries.add().CopyFrom(e)
    _builds_changed(slide)


def _builds_changed(slide: "Slide") -> None:
    p = slide._package
    node = slide._node
    node.build_event_count = len(slide._slide.buildChunks)
    node.build_event_count_cache_version = _STALE_CACHE
    node.has_explicit_builds_cache_version = _STALE_CACHE
    node.ClearField("has_explicit_builds")
    node.thumbnailsAreDirty = True
    p.mark_changed(slide._node_id)
    p.mark_changed(slide._slide_id)
    p.mark_changed(METADATA_ID)
