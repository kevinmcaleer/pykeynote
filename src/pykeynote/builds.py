"""Build animations: how a slide's title, body or shapes appear on click.

A slide lists its builds in ``KN.SlideArchive.builds``, one
``KN.BuildArchive`` per animated object. The order they play in is
``KN.SlideArchive.buildChunks``: one ``KN.BuildChunkArchive`` per click
("event"), so a body built by paragraph has a chunk per paragraph. Chunks
name their build by a UUID, which is also recorded as the build's identity
in the slide's component.

The field values written here are the ones Keynote writes for a default
Dissolve, Move In, Wipe or Fade and Move build. A chunk's ``automatic`` and
``delay`` say when it starts: on a click, or by itself after the step
before. A direction, such as Wipe's Right to Left, is
``animationAttributes.direction``, which slide transitions share.
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

# Friendly names for effects whose ids differ from the "apple:<name> character" pattern.
EFFECT_ALIASES = {
    "wipe": "apple:wipe",
}

# Keynote's direction values, shared by builds and transitions. Keynote leaves
# the field out for an effect's default direction.
DIRECTIONS = {
    "from left": 11,
    "from right": 12,
    "from top": 13,
    "from bottom": 14,
}
_DIRECTION_SYNONYMS = {
    "left": "from left",
    "left to right": "from left",
    "right": "from right",
    "right to left": "from right",
    "top": "from top",
    "top to bottom": "from top",
    "bottom": "from bottom",
    "bottom to top": "from bottom",
}
_DIRECTION_NAMES = {v: k for k, v in DIRECTIONS.items()}

# Effects that take a direction, with the one Keynote uses when the field is left out.
_DIRECTIONAL = {
    "apple:wipe": "from left",
    "apple:move in character": None,
    "apple:move out character": None,
    "apple:fade and move character": None,
}

STARTS = ("on click", "after previous", "with previous")

Target = Union[str, int]

@dataclass(frozen=True)
class Build:
    """One build on a slide."""

    target: Union[str, int]  # "title", "body", or the identifier of another drawable
    kind: str  # "in" or "out"
    effect: str  # e.g. "dissolve", "move in"
    delivery: str  # Keynote's delivery name, e.g. "All at Once", "By Paragraph"
    duration: float
    steps: int  # steps this build takes: one, or one per bullet
    effect_id: str  # Keynote's own effect id, e.g. "apple:dissolve character"
    start: str = "on click"  # when its first step starts: "on click", "after previous" or "with previous"
    delay: float = 0.0  # seconds its first step waits after it is due to start
    direction: Optional[str] = None  # e.g. "from left", for effects that move; None if it has none or isn't known


def _effect_id(name: str) -> str:
    if ":" in name:
        return name
    key = " ".join(name.strip().lower().replace("_", " ").replace("-", " ").split())
    return EFFECT_ALIASES.get(key, "apple:" + key + " character")


def _effect_name(effect_id: str) -> str:
    name = effect_id.split(":", 1)[-1]
    return name[: -len(" character")] if name.endswith(" character") else name


def direction_value(direction: str) -> int:
    """Keynote's number for a direction such as ``"from left"`` (also ``"left to right"``, ``"from-left"``)."""
    key = " ".join(direction.strip().lower().replace("_", " ").replace("-", " ").split())
    key = _DIRECTION_SYNONYMS.get(key, key)
    if key not in DIRECTIONS:
        raise ValueError(f"direction must be one of {', '.join(DIRECTIONS)}, not {direction!r}")
    return DIRECTIONS[key]


def direction_name(value: int, default: Optional[str] = None) -> Optional[str]:
    """The name of a stored direction value; ``default`` when Keynote left it out (0)."""
    if not value:
        return default
    return _DIRECTION_NAMES.get(value, str(value))


def _set_direction(animation: Any, effect_id: str, direction: Optional[str], directional: dict, what: str) -> None:
    animation.ClearField("direction")
    if direction is None:
        return
    if effect_id not in directional and effect_id.startswith("apple:"):
        known = ", ".join(sorted(_effect_name(e) for e in directional))
        raise ValueError(f"the {_effect_name(effect_id)!r} {what} has no direction; effects with one: {known}")
    value = direction_value(direction)
    if direction_name(value) != directional.get(effect_id):
        animation.direction = value


def _target_from_ref(slide: "Slide", drawable_id: int) -> Union[str, int]:
    name = _target_name(slide, drawable_id)
    if name == drawable_id:
        shape = slide._subtitle_shape()
        if shape is not None and shape.identifier == drawable_id:
            return "subtitle"
    return name


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
    first_chunk: dict = {}
    for ref in slide._slide.buildChunks:
        chunk = p.deref(ref)
        build_id = chunk.build.identifier
        steps[build_id] = steps.get(build_id, 0) + 1
        first_chunk.setdefault(build_id, chunk)
    first = {build_id: i for i, build_id in enumerate(steps)}
    refs = sorted(slide._slide.builds, key=lambda r: first.get(r.identifier, len(first)))
    out = []
    for ref in refs:
        b = p.deref(ref)
        a = b.attributes.animationAttributes
        chunk = first_chunk.get(ref.identifier)
        out.append(
            Build(
                target=_target_from_ref(slide, b.drawable.identifier),
                kind=a.animation_type.lower(),
                effect=_effect_name(a.effect),
                delivery=b.delivery,
                duration=a.duration,
                steps=steps.get(ref.identifier, 0),
                effect_id=a.effect,
                start=_start_of(chunk),
                delay=round(chunk.delay, 6) if chunk is not None else 0.0,
                direction=direction_name(a.direction, _DIRECTIONAL.get(a.effect)),
            )
        )
    return out


def _start_of(chunk: Any) -> str:
    if chunk is None or not chunk.automatic:
        return "on click"
    return "after previous"


def _start_name(start: str) -> str:
    key = " ".join(start.strip().lower().replace("_", " ").replace("-", " ").split())
    key = {"click": "on click", "after": "after previous", "with": "with previous"}.get(key, key)
    if key not in STARTS:
        raise ValueError(f"start must be one of {', '.join(STARTS)}, not {start!r}")
    return key


def _resolve_target(slide: "Slide", target: Target) -> int:
    s = slide._slide
    shown = {r.identifier for r in s.drawables_z_order}
    target = getattr(target, "identifier", target)  # a Shape, Table or Chart
    if target == "subtitle":
        shape = slide._subtitle_shape()
        if shape is None or shape.identifier not in shown:
            raise ValueError(f"slide {slide.index} has no subtitle; add one with add_subtitle()")
        return shape.identifier
    if target in ("title", "body"):
        field = "titlePlaceholder" if target == "title" else "bodyPlaceholder"
        if not s.HasField(field) or getattr(s, field).identifier not in shown:
            raise ValueError(f"the {slide.layout!r} layout doesn't show a {target} on slide {slide.index}")
        return getattr(s, field).identifier
    if isinstance(target, int) and target in shown:
        return target
    raise ValueError(f"build target must be 'title', 'subtitle', 'body' or a drawable on the slide, not {target!r}")


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
    start: str = "on click",
    delay: float = 0.0,
    direction: Optional[str] = None,
) -> Build:
    p = slide._package
    s = slide._slide
    drawable_id = _resolve_target(slide, target)
    target = drawable_id if not isinstance(target, str) else target
    if kind not in _KINDS:
        raise ValueError(f"kind must be 'in' or 'out', not {kind!r}")
    start = _start_name(start)
    if delay < 0:
        raise ValueError("delay can't be negative")
    effect_id = _effect_id(effect)
    is_body = target == "body"
    if delivery is None:
        delivery = "by paragraph" if is_body and len(slide.paragraphs) > 1 else "all at once"
    if delivery.lower() not in _DELIVERY_NAMES:
        raise ValueError(f"delivery must be one of {', '.join(sorted(_DELIVERY_NAMES))}, not {delivery!r}")
    delivery_name = _DELIVERY_NAMES[delivery.lower()]
    steps = 1
    if delivery_name == "By Paragraph":
        if target not in ("title", "body"):
            raise ValueError("only the title and body can be built by bullet")
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
    a.effect = effect_id
    a.duration = float(duration)
    _set_direction(a, effect_id, direction, _DIRECTIONAL, "build")
    a.delay = 0.0
    a.random_number_seed = random.randrange(1, 2**31)
    a.writing_direction_is_rtl = False
    _set_custom_defaults(attrs, effect_id)
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
        # The start and delay belong to the first step; later bullets come on a click.
        chunk.delay = float(delay) if step == 1 else 0.0
        chunk.duration = float(duration)
        chunk.automatic = step == 1 and start != "on click"
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


def _set_custom_defaults(attrs: Any, effect_id: str) -> None:
    """The effect-specific options Keynote writes for a new build of this effect."""
    if effect_id == "apple:wipe":
        return  # Keynote writes no text delivery or delivery option for Wipe
    attrs.custom_textDelivery = attrs.kTextDeliveryByObject
    attrs.custom_deliveryOption = attrs.kDeliveryOptionForward
    if effect_id == "apple:move in character":
        attrs.custom_bounce = True
        attrs.custom_deliveryOption = attrs.kDeliveryOptionBackward
    elif effect_id == "apple:fade and move character":
        attrs.custom_deliveryOption = attrs.kDeliveryOptionBackward
        attrs.custom_travel_distance = 1.0


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
